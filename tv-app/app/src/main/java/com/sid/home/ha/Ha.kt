package com.sid.home.ha

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** One Home Assistant entity, as the Hub sees it: a state and a bag of attributes. */
data class Entity(val id: String, val state: String, val attrs: JsonObject = JsonObject(emptyMap()), val lastChanged: String? = null) {
    fun str(key: String): String? = (attrs[key] as? JsonPrimitive)?.contentOrNull
    fun num(key: String): Double? = (attrs[key] as? JsonPrimitive)?.let { it.doubleOrNull ?: it.contentOrNull?.toDoubleOrNull() }
    fun bool(key: String): Boolean? = (attrs[key] as? JsonPrimitive)?.contentOrNull?.toBooleanStrictOrNull()
    fun arr(key: String): JsonArray? = attrs[key] as? JsonArray
    fun obj(key: String): JsonObject? = attrs[key] as? JsonObject
    val number: Double? get() = state.toDoubleOrNull()
    fun ints(key: String): List<Int>? = arr(key)?.mapNotNull { (it as? JsonPrimitive)?.doubleOrNull?.toInt() }
}

/** What every screen reads: the entities, whether Home Assistant is connected, and the calendar's events. */
class HomeState {
    private val _entities = MutableStateFlow<Map<String, Entity>>(emptyMap())
    val entities: StateFlow<Map<String, Entity>> = _entities.asStateFlow()
    val connected = MutableStateFlow(false)
    val events = MutableStateFlow<List<JsonObject>>(emptyList())
    val demo = MutableStateFlow(false)
    /** When the state shown was saved on the TV (null: it's live from Home Assistant). */
    val savedAt = MutableStateFlow<Long?>(null)
    /** Changes waiting for Home Assistant to come back. */
    val pending = MutableStateFlow(0)

    fun replace(all: Map<String, Entity>) { _entities.value = all }

    /** Show a change before Home Assistant confirms it (it's offline; the queue sends it when it's back). */
    fun optimistic(id: String, state: String, attrs: JsonObject? = null) = _entities.update { m ->
        val e = m[id] ?: return@update m
        m + (id to e.copy(state = state, attrs = if (attrs == null) e.attrs else JsonObject(e.attrs + attrs.filterKeys { it != "entity_id" })))
    }
    fun put(e: Entity) = _entities.update { it + (e.id to e) }
    fun remove(id: String) = _entities.update { it - id }

    /** Several changes as one new map (null: the entity is gone). */
    fun apply(changes: Map<String, Entity?>) = _entities.update { m ->
        LinkedHashMap(m).apply { for ((id, e) in changes) if (e == null) remove(id) else put(id, e) }
    }
}

val json = Json { ignoreUnknownKeys = true }

fun entityFrom(o: JsonObject): Entity = Entity(
    id = o["entity_id"]!!.jsonPrimitive.content,
    state = o["state"]?.jsonPrimitive?.contentOrNull ?: "unknown",
    attrs = (o["attributes"] as? JsonObject) ?: JsonObject(emptyMap()),
    lastChanged = (o["last_changed"] as? JsonPrimitive)?.contentOrNull,
)

/** Build a service call's data: callService("light", "toggle", "entity_id" to id). */
fun data(vararg pairs: Pair<String, Any?>): JsonObject = buildJsonObject {
    for ((k, v) in pairs) when (v) {
        null -> put(k, JsonNull)
        is String -> put(k, v)
        is Number -> put(k, v)
        is Boolean -> put(k, v)
        is List<*> -> put(k, JsonArray(v.map { x -> if (x is Number) JsonPrimitive(x) else JsonPrimitive(x.toString()) }))
        is JsonElement -> put(k, v)
        else -> put(k, v.toString())
    }
}

/** Anything that can change the home: Home Assistant itself, or nothing at all in demo mode. */
interface Actions {
    fun callService(domain: String, service: String, data: JsonObject)
}

/**
 * Home Assistant over its websocket API, the same feed the Hub uses: every state once, then each change as it
 * happens. Reconnects with backoff, forever; while it's down the screens keep showing the last state, marked offline.
 */
class HaClient(private val baseUrl: String, private val token: String, private val home: HomeState) : Actions {
    private val queue = OfflineQueue(home)
    @Volatile private var authed = false
    /** Tells the person when something can't be done right now (a toast). */
    var notice: ((String) -> Unit)? = null
    private val http = OkHttpClient.Builder().pingInterval(30, TimeUnit.SECONDS).readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val ids = AtomicInteger(10)
    private var socket: WebSocket? = null
    private var backoffMs = 1000L

    fun start() = connect()

    private companion object { const val BATCH_MS = 100L }

    private fun connect() {
        val ws = baseUrl.replaceFirst("http", "ws") + "/api/websocket"
        socket = http.newWebSocket(Request.Builder().url(ws).build(), object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) = handle(webSocket, json.parseToJsonElement(text).jsonObject)
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = retry()
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = retry()
        })
    }

    private fun retry() {
        authed = false
        home.connected.value = false
        socket = null
        scope.launch {
            delay(backoffMs)
            backoffMs = (backoffMs * 2).coerceAtMost(30_000)
            connect()
        }
    }

    private fun handle(ws: WebSocket, m: JsonObject) {
        when (m["type"]?.jsonPrimitive?.content) {
            "auth_required" -> ws.send(buildJsonObject { put("type", "auth"); put("access_token", token) }.toString())
            "auth_ok" -> {
                backoffMs = 1000L
                authed = true
                // back: send what was changed while away, then take Home Assistant's whole state as the truth
                for ((d, sv, data) in queue.drain()) send(ws, d, sv, data)
                ws.send(buildJsonObject { put("id", 1); put("type", "get_states") }.toString())
                ws.send(buildJsonObject { put("id", 2); put("type", "subscribe_events"); put("event_type", "state_changed") }.toString())
                home.connected.value = true
            }
            "auth_invalid" -> home.connected.value = false
            "result" -> if (m["id"]?.jsonPrimitive?.intOrNull == 1) {
                val all = m["result"]?.jsonArray?.map { entityFrom(it.jsonObject) } ?: emptyList()
                home.replace(all.associateBy { it.id })
                home.savedAt.value = null
                scope.launch { refreshCalendars() } // now the calendars are known
            }
            "event" -> {
                val d = m["event"]?.jsonObject?.get("data")?.jsonObject ?: return
                val id = d["entity_id"]?.jsonPrimitive?.content ?: return
                val new = d["new_state"]
                stage(id, if (new == null || new is JsonNull) null else entityFrom(new.jsonObject))
            }
        }
    }

    private val staged = LinkedHashMap<String, Entity?>()
    private var flushing = false

    /**
     * Changes are applied together every BATCH_MS instead of one by one: during music sync Home Assistant sends dozens
     * of events a second, and each one copied the whole entity map (hundreds of entries): garbage the TV's collector
     * then had to clear, pausing the UI thread. The screens only look 5 times a second anyway.
     */
    private fun stage(id: String, e: Entity?) {
        synchronized(staged) {
            staged[id] = e
            if (flushing) return
            flushing = true
        }
        scope.launch {
            delay(BATCH_MS)
            val batch = synchronized(staged) { flushing = false; LinkedHashMap(staged).also { staged.clear() } }
            home.apply(batch)
        }
    }

    override fun callService(domain: String, service: String, data: JsonObject) {
        val ws = socket
        if (authed && ws != null && send(ws, domain, service, data)) return
        if (!queue.add(domain, service, data)) notice?.invoke("Can't reach the home system right now")
    }

    private fun send(ws: WebSocket, domain: String, service: String, data: JsonObject) = ws.send(buildJsonObject {
        put("id", ids.incrementAndGet()); put("type", "call_service")
        put("domain", domain); put("service", service); put("service_data", data)
    }.toString())

    /** The next week's events from every calendar (the Hub's calendar card and the screensaver's "next" line). */
    suspend fun refreshCalendars() {
        val cals = home.entities.value.keys.filter { it.startsWith("calendar.") }
        val start = java.time.LocalDate.now().atStartOfDay(java.time.ZoneId.systemDefault())
        val end = start.plusDays(7)
        var reached = false
        val events = cals.flatMap { cal ->
            runCatching {
                val req = Request.Builder().url("$baseUrl/api/calendars/$cal?start=${start.toInstant()}&end=${end.toInstant()}")
                    .header("Authorization", "Bearer $token").build()
                http.newCall(req).execute().use { r ->
                    reached = true
                    if (!r.isSuccessful) emptyList()
                    else json.parseToJsonElement(r.body!!.string()).jsonArray.map {
                        JsonObject(it.jsonObject + ("cal" to JsonPrimitive(cal)))
                    }
                }
            }.getOrDefault(emptyList())
        }
        if (reached) home.events.value = events.sortedBy { eventStart(it) } // unreachable: keep the last week we had
    }

    fun refreshCalendarsLater() = scope.launch { while (true) { delay(5 * 60_000); refreshCalendars() } }
}

fun eventStart(e: JsonObject): String {
    val s = e["start"]?.jsonObject ?: return ""
    return s["dateTime"]?.jsonPrimitive?.contentOrNull ?: (s["date"]?.jsonPrimitive?.contentOrNull + "T00:00:00")
}

/** Demo mode: the Hub's made-up household (frontend/hub/demo.js, exported to assets/demo.json), nothing connected. */
object Demo : Actions {
    var onCall: ((String) -> Unit)? = null
    fun load(home: HomeState, text: String) {
        val root = json.parseToJsonElement(text).jsonObject
        home.replace(root["entities"]!!.jsonObject.mapValues { (id, v) ->
            entityFrom(JsonObject(v.jsonObject + ("entity_id" to JsonPrimitive(id))))
        })
        home.events.value = root["events"]?.jsonArray?.map { it.jsonObject } ?: emptyList()
        home.connected.value = true
        home.demo.value = true
    }
    override fun callService(domain: String, service: String, data: JsonObject) { onCall?.invoke("Demo: nothing here is connected") }
}

