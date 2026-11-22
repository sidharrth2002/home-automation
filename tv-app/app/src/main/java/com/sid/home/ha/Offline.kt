package com.sid.home.ha

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.sample
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File

/**
 * The home's last known state, kept on the TV: loaded at start (so every page shows something with the Mac off,
 * marked offline), saved at most every SAVE_EVERY_MS while things change, and when the app goes to the background.
 * (Not "after a quiet spell": Home Assistant sends something every couple of seconds, so it's never quiet.)
 */
class Snapshot(private val file: File) {
    fun load(home: HomeState): Boolean = runCatching {
        val root = json.parseToJsonElement(file.readText()).jsonObject
        home.replace(root["entities"]!!.jsonObject.mapValues { (id, v) -> entityFrom(JsonObject(v.jsonObject + ("entity_id" to JsonPrimitive(id)))) })
        home.events.value = root["events"]?.jsonArray?.map { it.jsonObject } ?: emptyList()
        home.savedAt.value = root["saved_at"]?.jsonPrimitive?.contentOrNull?.toLongOrNull()
        true
    }.getOrDefault(false)

    private val SAVE_EVERY_MS = 10_000L

    @OptIn(FlowPreview::class)
    fun keepSaved(home: HomeState, scope: CoroutineScope) = scope.launch {
        combine(home.entities, home.events) { e, ev -> e to ev }.drop(1).sample(SAVE_EVERY_MS).collect { write(it.first, it.second) }
    }

    /** Save now (the app is going to the background). */
    fun flush(home: HomeState) = write(home.entities.value, home.events.value)

    @Synchronized
    private fun write(entities: Map<String, Entity>, events: List<JsonObject>) {
            if (entities.isEmpty() || entities.containsKey("__demo__")) return
            val doc = buildJsonObject {
                put("saved_at", System.currentTimeMillis().toString())
                put("entities", JsonObject(entities.mapValues { (_, e) ->
                    buildJsonObject { put("state", e.state); put("attributes", e.attrs); e.lastChanged?.let { put("last_changed", it) } } }))
                put("events", JsonArray(events))
            }
            runCatching {
                val tmp = File(file.path + ".tmp"); tmp.writeText(doc.toString()); tmp.renameTo(file) // never a half-written file
            }
    }
}

/**
 * Changes made while Home Assistant can't be reached: applied to the screen at once, and sent when it's back.
 *
 * Only the latest wanted state per entity is kept, and a toggle is stored as the state it led to (turn_on/turn_off),
 * so replaying can't flip anything twice. Changes older than MAX_AGE_MS are dropped (no lamp coming on hours later).
 * One-off actions (scripts: the scenes; music and remote commands) aren't queued at all: they'd surprise you later.
 */
class OfflineQueue(private val home: HomeState, private val clock: () -> Long = System::currentTimeMillis) {
    private data class Pending(val domain: String, val service: String, val data: JsonObject, val at: Long)
    private val pending = LinkedHashMap<String, Pending>()
    private val oneOff = setOf("script", "remote", "media_player")

    companion object { const val MAX_AGE_MS = 15 * 60_000L }

    /** Queue a call (and show its effect now). Returns false if it's a one-off that can't wait. */
    @Synchronized
    fun add(domain: String, service: String, data: JsonObject): Boolean {
        val id = data["entity_id"]?.jsonPrimitive?.contentOrNull
        if (domain in oneOff || id == null) return false
        val now = clock()
        if (service == "toggle") {
            val on = home.entities.value[id]?.state != "on"
            pending["power:$id"] = Pending(domain, if (on) "turn_on" else "turn_off", buildJsonObject { put("entity_id", id) }, now)
            home.optimistic(id, if (on) "on" else "off")
        } else {
            if (service == "turn_on" || service == "turn_off") pending.remove("power:$id")
            pending["$service:$id"] = Pending(domain, service, data, now)
            when (service) {
                "turn_on" -> home.optimistic(id, "on", data)
                "turn_off" -> home.optimistic(id, "off")
                "select_option" -> data["option"]?.jsonPrimitive?.contentOrNull?.let { home.optimistic(id, it) }
                "set_value" -> data["value"]?.jsonPrimitive?.contentOrNull?.let { home.optimistic(id, it) }
            }
        }
        home.pending.value = pending.size
        return true
    }

    /** Everything still worth sending, oldest first; the queue is then empty. */
    @Synchronized
    fun drain(): List<Triple<String, String, JsonObject>> {
        val fresh = clock() - MAX_AGE_MS
        val out = pending.values.filter { it.at >= fresh }.sortedBy { it.at }.map { Triple(it.domain, it.service, it.data) }
        pending.clear()
        home.pending.value = 0
        return out
    }
}
