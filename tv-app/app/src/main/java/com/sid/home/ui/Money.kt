package com.sid.home.ui

import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import java.text.NumberFormat
import java.time.LocalDate
import java.util.Locale
import kotlin.math.abs

// ── small helpers, as in the Hub ──
private fun JsonObject.s(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull
private fun JsonObject.d(k: String) = (this[k] as? JsonPrimitive)?.let { it.doubleOrNull ?: it.contentOrNull?.toDoubleOrNull() }
private fun JsonObject.b(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull?.toBooleanStrictOrNull()
private fun JsonObject.list(k: String) = (this[k] as? JsonArray)?.map { it.jsonObject } ?: emptyList()

fun gbp(v: Double?, dp: Int = 0): String = if (v == null) "—" else NumberFormat.getCurrencyInstance(Locale.UK).apply {
    maximumFractionDigits = dp; minimumFractionDigits = dp }.format(v)
fun signed(v: Double?, f: (Double) -> String) = if (v == null) "—" else (if (v >= 0) "+" else "−") + f(abs(v))
fun pct(v: Double?, dp: Int = 1) = signed(v) { "%.${dp}f%%".format(it) }
fun pence(p: Double?) = if (p == null) "—" else if (p >= 1000) gbp(p / 100, 2) else "%.2fp".format(p)
private fun upDown(v: Double?) = if ((v ?: 0.0) >= 0) Hub.up else Hub.down

val RANGES = linkedMapOf("1M" to 31, "3M" to 92, "6M" to 183, "1Y" to 366, "3Y" to 1096, "5Y" to 1827)
typealias Series = List<Pair<Int, Double>>
fun Series.since(days: Int): Series = if (isEmpty()) this else { val cut = last().first - days; filter { it.first >= cut } }
fun Series.change(): Double? = if (size > 1) (last().second / first().second - 1) * 100 else null

fun seriesOf(ctx: Ctx, sedol: String): Series = ctx.s["sensor.investment_${sedol.lowercase()}"]?.arr("series")?.mapNotNull {
    val p = it.jsonArray; val d = (p[0] as? JsonPrimitive)?.doubleOrNull; val v = (p[1] as? JsonPrimitive)?.doubleOrNull
    if (d != null && v != null) d.toInt() to v else null
} ?: emptyList()

/** Today's holdings valued over time from each fund's price history (portfolioSeries in the Hub). */
fun portfolioSeries(ctx: Ctx, holdings: List<JsonObject>): Series {
    val all = holdings.map { (it.d("units") ?: 0.0) to seriesOf(ctx, it.s("sedol") ?: "") }.filter { it.second.isNotEmpty() }
    if (all.isEmpty()) return emptyList()
    val start = all.maxOf { it.second.first().first }
    val days = all.flatMap { s -> s.second.map { it.first } }.filter { it >= start }.toSortedSet()
    val idx = IntArray(all.size)
    return days.map { d ->
        d to all.withIndex().sumOf { (k, x) ->
            val pts = x.second
            while (idx[k] + 1 < pts.size && pts[idx[k] + 1].first <= d) idx[k]++
            x.first * pts[idx[k]].second / 100
        }
    }
}

/** Money is hidden until the eye is pressed, and stays as chosen (like the Hub's localStorage switch). */
object Privacy {
    private fun prefs(c: Context) = c.getSharedPreferences("hub", Context.MODE_PRIVATE)
    private var state: androidx.compose.runtime.MutableState<Boolean>? = null
    /** Whether amounts show, shared by every page; read from storage once. */
    fun state(c: Context) = state ?: mutableStateOf(prefs(c).getBoolean("showMoney", false)).also { state = it }
    fun shown(c: Context) = state(c).value
    fun set(c: Context, on: Boolean) { state(c).value = on; prefs(c).edit().putBoolean("showMoney", on).apply() }
}

@Composable
private fun EyeButton() {
    val context = LocalContext.current
    val show = Privacy.state(context).value
    Pressable(onClick = { Privacy.set(context, !show) }, shape = CircleShape) {
        Box(Modifier.padding(6.dp)) { HubIcon(HubIcons.eye, if (show) Hub.ink else Hub.ink3, 14.dp) }
    }
}

@Composable
fun Money(text: String, show: Boolean, style: androidx.compose.ui.text.TextStyle, modifier: Modifier = Modifier) =
    Text(text, style = style, maxLines = 1, modifier = modifier.then(if (show) Modifier else Modifier.blur(7.dp)))

/** The Allocation page: where the money is (by type, then each provider's accounts) and what it's invested in. */
@Composable
fun AllocationCard(ctx: Ctx) {
    val a = ctx.s[Ids2.INVEST]?.attrs ?: return
    val show = Privacy.state(LocalContext.current).value
    HubCard {
        CardHead("Allocation", HubIcons.chart) { EyeButton() }
        Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
            Column(Modifier.weight(1f)) {
                Kicker("Where it is")
                Allocation(a.list("accounts"))
                Providers(ctx, a.list("accounts"), a.list("sources"), show)
            }
            Column(Modifier.weight(1f)) { Exposure(a["exposure"] as? JsonObject, show, all = true) }
        }
    }
}

// account types: the same palette slots as the Hub (ACCOUNT_TYPES / ALLOC in app.js)
private val ALLOC = listOf(0xFF3987E5, 0xFFD95926, 0xFF199E70, 0xFFC98500, 0xFFD55181, 0xFF008300, 0xFF9085E9, 0xFFE66767).map { Color(it) }
private val TYPES = mapOf("isa" to ("ISA" to 0), "gia" to ("GIA" to 1), "savings" to ("Savings" to 2), "premium_bonds" to ("Premium Bonds" to 3),
    "cash" to ("Cash" to 4), "current" to ("Cash" to 4), "sipp" to ("Pension" to 5), "pension" to ("Pension" to 5), "lisa" to ("LISA" to 6), "other" to ("Other" to 7))
private fun typeOf(t: String?) = TYPES[t] ?: TYPES.getValue("other")

@Composable
fun MoneyCard(ctx: Ctx, onHolding: (String) -> Unit) {
    val e = ctx.s[Ids2.INVEST] ?: return
    val a = e.attrs
    val show = Privacy.state(LocalContext.current).value
    var range by rememberSaveable { mutableStateOf("1Y") }
    var src by rememberSaveable { mutableStateOf("all") }
    var all by rememberSaveable { mutableStateOf(false) }
    val holdingsAll = a.list("holdings")
    val sources = a.list("sources")
    val srcName = { id: String -> sources.firstOrNull { it.s("id") == id }?.s("name") ?: id }
    val holders = holdingsAll.mapNotNull { it.s("source") }.distinct()
    val holdings = if (src == "all") holdingsAll else holdingsAll.filter { it.s("source") == src }
    val stock = holdingsAll.sumOf { it.d("value") ?: 0.0 }.takeIf { it > 0 } ?: 1.0
    val port = portfolioSeries(ctx, holdingsAll)
    val ranged = port.since(RANGES.getValue(range))
    HubCard {
        CardHead("Investments", HubIcons.chart) {
            parseTime(a.s("updated"))?.let { Kicker("Updated " + it.toLocalTime().toString().take(5)) }
            Spacer(Modifier.width(10.dp))
            EyeButton()
        }
        if (a.s("status") == "paused") Text("Refresh paused · ${a.s("paused_reason").orEmpty()}", style = Hub.text(9.sp, Hub.warn),
            modifier = Modifier.padding(bottom = 8.dp), maxLines = 2)
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            // overview: total, today, all time, the chart, then exposure
            Column(Modifier.weight(4f)) {
                Money(gbp(e.number), show, Hub.text(36.sp, family = Hub.serif))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    a.d("day_change")?.let { dc -> Row { Money(signed(dc) { gbp(it) }, show, Hub.text(9.sp, upDown(dc))); Text(" · ${pct(a.d("day_change_pct"), 2)} today", style = Hub.text(9.sp, upDown(dc))) } }
                    a.d("gain")?.let { g -> Row { Money(signed(g) { gbp(it) }, show, Hub.text(9.sp, upDown(g))); Text(" · ${pct(a.d("gain_pct"))} all time", style = Hub.text(9.sp, upDown(g))) } }
                }
                if (port.size > 1) {
                    Row(Modifier.padding(top = 12.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Kicker("Today's ${if (holdingsAll.all { seriesOf(ctx, it.s("sedol") ?: "").isNotEmpty() }) "holdings" else "priced funds"} over $range")
                        Text("  ${pct(ranged.change())}", style = Hub.text(8.sp, upDown(ranged.change()), 600))
                    }
                    RangeTabs(range, port.last().first - port.first().first) { range = it }
                    LineChart(ranged, Modifier.fillMaxWidth().height(190.dp).padding(top = 10.dp))
                }
            }
            // holdings
            Column(Modifier.weight(5f)) {
                if (holders.size > 1) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    Segmented(listOf("all") + holders, src, label = { if (it == "all") "All" else srcName(it) }, modifier = Modifier.width(200.dp),
                        onSelect = { src = it; all = false })
                }
                Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 6.dp)) {
                    Kicker("Holding", modifier = Modifier.weight(1f)); Kicker("3M", modifier = Modifier.width(60.dp)); Kicker("Today · all time")
                }
                val biggest = holdings.maxOfOrNull { it.d("value") ?: 0.0 }?.takeIf { it > 0 } ?: 1.0
                // a list of its own: with "Show all" it scrolls inside this column as the focus moves (the page doesn't)
                androidx.compose.foundation.lazy.LazyColumn(Modifier.weight(1f, fill = false)) {
                    items((if (all) holdings else holdings.take(7)).size) { i ->
                        val h = (if (all) holdings else holdings.take(7))[i]
                        HoldingRow(ctx, h, stock, biggest, holders.size > 1, srcName, show) { onHolding(h.s("sedol") ?: "") }
                    }
                    if (holdings.size > 7) item {
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                            Pressable(onClick = { all = !all }, shape = CircleShape, color = Color.White.copy(alpha = .06f)) {
                                Text(if (all) "Show fewer" else "Show all ${holdings.size}", style = Hub.text(10.sp, Hub.ink2), modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
                            }
                        }
                    }
                }
                a.d("cash")?.takeIf { it > 0 }?.let { c -> Row(Modifier.padding(top = 8.dp)) {
                    Text("Plus ", style = Hub.text(8.sp, Hub.ink3)); Money(gbp(c), show, Hub.text(8.sp, Hub.ink3)); Text(" uninvested cash in the investment accounts.", style = Hub.text(8.sp, Hub.ink3))
                } }
            }
        }
    }
}

@Composable
fun RangeTabs(range: String, span: Int, onPick: (String) -> Unit) =
    Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        for ((k, days) in RANGES) if (span >= days * 0.8 || k == "1M") {
            val on = k == range
            Pressable(onClick = { onPick(k) }, shape = CircleShape, color = if (on) Color.White.copy(alpha = .14f) else Color.Transparent) {
                Text(k, style = Hub.text(8.sp, if (on) Hub.ink else Hub.ink3, 600, Hub.mono), modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp))
            }
        }
    }

/** The Hub's line chart: a filled line, coloured by whether it went up, with an optional reference line. */
@Composable
fun LineChart(pts: Series, modifier: Modifier = Modifier, ref: Double? = null) {
    val up = (pts.change() ?: 0.0) >= 0
    val col = if (up) Hub.up else Hub.down
    Canvas(modifier) {
        if (pts.size < 2) return@Canvas
        val lo = minOf(pts.minOf { it.second }, ref ?: Double.MAX_VALUE); val hi = maxOf(pts.maxOf { it.second }, ref ?: -Double.MAX_VALUE)
        val span = (hi - lo).takeIf { it > 0 } ?: 1.0
        val x0 = pts.first().first; val xs = (pts.last().first - x0).coerceAtLeast(1)
        fun px(p: Pair<Int, Double>) = Offset((p.first - x0).toFloat() / xs * size.width, (size.height * (1 - (p.second - lo) / span)).toFloat())
        val line = Path().apply { pts.forEachIndexed { i, p -> val o = px(p); if (i == 0) moveTo(o.x, o.y) else lineTo(o.x, o.y) } }
        val fill = Path().apply { addPath(line); lineTo(size.width, size.height); lineTo(0f, size.height); close() }
        drawPath(fill, Brush.verticalGradient(listOf(col.copy(alpha = .35f), Color.Transparent)))
        drawPath(line, col, style = Stroke(1.6.dp.toPx()))
        ref?.let { r -> val y = (size.height * (1 - (r - lo) / span)).toFloat()
            drawLine(Hub.ink3, Offset(0f, y), Offset(size.width, y), 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(5f, 5f))) }
    }
}

@Composable
private fun Spark(pts: Series, modifier: Modifier) {
    if (pts.size < 2) { Box(modifier, contentAlignment = Alignment.Center) { Text("—", style = Hub.text(10.sp, Hub.ink3)) }; return }
    val col = upDown(pts.change())
    Canvas(modifier) {
        val lo = pts.minOf { it.second }; val span = (pts.maxOf { it.second } - lo).takeIf { it > 0 } ?: 1.0
        val path = Path(); pts.forEachIndexed { i, p ->
            val x = i.toFloat() / (pts.size - 1) * size.width; val y = (size.height * (1 - (p.second - lo) / span)).toFloat()
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y) }
        drawPath(path, col, style = Stroke(1.2.dp.toPx()))
    }
}

@Composable
private fun HoldingRow(ctx: Ctx, h: JsonObject, stock: Double, biggest: Double, tag: Boolean, srcName: (String) -> String, show: Boolean, onClick: () -> Unit) {
    val v = h.d("value") ?: 0.0
    val unit = h.s("unit_type")?.takeIf { it.any(Char::isLetter) } ?: h.s("account")
    Pressable(onClick = onClick, modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp), shape = RoundedCornerShape(11.dp),
        color = Color.White.copy(alpha = .035f), scale = 1.02f) {
        Box {
            Box(Modifier.align(Alignment.BottomStart).padding(start = 10.dp, bottom = 3.dp).fillMaxWidth((v / biggest).toFloat() * .95f).height(1.5.dp)
                .background(Color.hsv(hueOf(h.s("sedol") ?: ""), .5f, .9f).copy(alpha = .5f)))
            Row(Modifier.padding(horizontal = 10.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(h.s("name").orEmpty(), style = Hub.text(10.sp, weight = 500), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (h.s("status") == "pending") Text("Settling" + (h.s("settles")?.let { " " + LocalDate.parse(it).let { d -> "${d.dayOfMonth} ${d.month.name.take(3).lowercase().replaceFirstChar(Char::uppercase)}" } } ?: ""),
                            style = Hub.text(7.sp, Hub.ink, 500), modifier = Modifier.padding(end = 5.dp).clip(CircleShape).background(Color.White.copy(alpha = .1f)).padding(horizontal = 5.dp, vertical = 1.dp))
                        Text("%.1f%%".format(v / stock * 100) + (if (tag) " · ${srcName(h.s("source") ?: "")}" else "") + " · ${unit.orEmpty()}",
                            style = Hub.text(8.sp, Hub.ink3), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
                Spark(seriesOf(ctx, h.s("sedol") ?: "").since(92), Modifier.width(52.dp).height(18.dp))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.width(96.dp), horizontalAlignment = Alignment.End) {
                    Money(gbp(v), show, Hub.text(10.sp, weight = 500, family = Hub.mono))
                    Row {
                        h.d("day_change_pct")?.let { Text(pct(it, 2), style = Hub.text(8.sp, upDown(it), family = Hub.mono)) }
                        h.d("gain_pct")?.let { Text(" " + pct(it), style = Hub.text(8.sp, upDown(it), family = Hub.mono)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun Allocation(accounts: List<JsonObject>) {
    val counted = accounts.filter { it.b("in_total") != false && (it.d("total") ?: 0.0) > 0 }
    val sum = counted.sumOf { it.d("total") ?: 0.0 }
    if (sum <= 0) return
    val segs = counted.groupBy { typeOf(it.s("type")).second }.map { (slot, xs) -> Triple(slot, typeOf(xs[0].s("type")).first, xs.sumOf { it.d("total") ?: 0.0 }) }.sortedBy { it.first }
    fun share(v: Double) = if (v / sum < .1) "%.1f%%".format(v / sum * 100) else "%.0f%%".format(v / sum * 100)
    Row(Modifier.padding(top = 8.dp).fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        for ((slot, _, v) in segs) Box(Modifier.weight(v.toFloat()).height(8.dp).background(ALLOC[slot]))
    }
    FlowRowSimple(Modifier.padding(top = 7.dp)) {
        for ((slot, label, v) in segs) Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(7.dp).clip(RoundedCornerShape(2.dp)).background(ALLOC[slot])); Spacer(Modifier.width(4.dp))
            Text("$label ", style = Hub.text(8.5.sp, Hub.ink2)); Text(share(v), style = Hub.text(8.sp, weight = 600, family = Hub.mono))
        }
    }
}

@Composable
private fun Providers(ctx: Ctx, accounts: List<JsonObject>, sources: List<JsonObject>, show: Boolean) {
    val ids = (sources.mapNotNull { it.s("id") } + accounts.mapNotNull { it.s("source") }).distinct().filter { id -> accounts.any { it.s("source") == id } }
    Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
        for (id in ids) {
            val src = sources.firstOrNull { it.s("id") == id }
            val rows = accounts.filter { it.s("source") == id }
            val total = rows.filter { it.b("in_total") != false }.sumOf { it.d("total") ?: 0.0 }
            val fresh = if (src?.s("kind") == "auto") "Live" + (parseTime(src.s("updated"))?.let { " · " + it.toLocalTime().toString().take(5) } ?: "")
            else src?.s("as_of")?.let { d -> LocalDate.parse(d).let { "As of ${it.dayOfMonth} ${it.month.name.take(3).lowercase().replaceFirstChar(Char::uppercase)}" } } ?: ""
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = .035f)).border(1.dp, Hub.line, RoundedCornerShape(12.dp)).padding(9.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(src?.s("name") ?: rows[0].s("provider") ?: id, style = Hub.text(10.sp, weight = 600)); Spacer(Modifier.width(6.dp))
                    Text(fresh, style = Hub.text(8.sp, Hub.ink3), modifier = Modifier.weight(1f), maxLines = 1)
                    Money(gbp(total), show, Hub.text(10.sp, weight = 500, family = Hub.mono))
                }
                for (x in rows) {
                    val excluded = x.b("in_total") == false
                    val kind = if (x.s("type") == "current") "Current account" else typeOf(x.s("type")).first
                    val meta = listOfNotNull(kind.takeIf { !it.equals(x.s("label") ?: "", true) },
                        x.d("interest_pct")?.let { "%.2f%%".format(it) },
                        x.s("matures")?.let { d -> LocalDate.parse(d).let { "matures ${it.month.name.take(3).lowercase().replaceFirstChar(Char::uppercase)} ${it.year}" } },
                        "not in total".takeIf { excluded }).joinToString(" · ")
                    Box(Modifier.fillMaxWidth().padding(top = 6.dp).height(1.dp).background(Hub.line))
                    Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(7.dp).clip(RoundedCornerShape(2.dp)).background(if (excluded) Color.Transparent else ALLOC[typeOf(x.s("type")).second])
                            .then(if (excluded) Modifier.border(1.dp, Hub.ink3, RoundedCornerShape(2.dp)) else Modifier)); Spacer(Modifier.width(7.dp))
                        Column(Modifier.weight(1f)) {
                            Text(x.s("label") ?: x.s("name").orEmpty(), style = Hub.text(9.5.sp), maxLines = 1)
                            if (meta.isNotEmpty()) Text(meta, style = Hub.text(7.5.sp, Hub.ink3), maxLines = 1)
                        }
                        Money(gbp(x.d("total")), show, Hub.text(9.5.sp, if (excluded) Hub.ink3 else Hub.ink, family = Hub.mono))
                    }
                }
                when (id) { "t212" -> T212Note(ctx, show); "nsandi" -> BondsNote(ctx, show) }
            }
        }
    }
}

@Composable
private fun Note(content: @Composable () -> Unit) = Column(Modifier.fillMaxWidth().padding(top = 6.dp)) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(Hub.line)); Box(Modifier.padding(start = 14.dp, top = 5.dp)) { content() }
}

@Composable
private fun T212Note(ctx: Ctx, show: Boolean) {
    val e = ctx.s[Ids2.T212] ?: return
    val it = e.obj("interest") ?: return
    Note { Row {
        Text("Interest daily · " + (it.d("est_rate_pct")?.let { r -> "≈ %.2f%% a year · ".format(r) } ?: ""), style = Hub.text(8.sp, Hub.ink2))
        it.d("month")?.let { m -> Money(gbp(m, 2), show, Hub.text(8.sp, Hub.ink2)); Text(" this month", style = Hub.text(8.sp, Hub.ink2)) }
    } }
}

@Composable
private fun BondsNote(ctx: Ctx, show: Boolean) {
    val e = ctx.s[Ids2.BONDS]
    Note {
        if (e == null || e.state == "not set up") Text("Prize checks not set up: ask your finance Claude to set your holder number.", style = Hub.text(8.sp, Hub.ink2))
        else Row {
            val month = e.str("last_draw")?.let { runCatching { java.time.YearMonth.parse(it).let { m -> "${m.month.name.lowercase().replaceFirstChar(Char::uppercase)} ${m.year}" } }.getOrNull() } ?: ""
            Text(when (e.state) { "won" -> "Won in the $month draw"; "no win" -> "No prize in $month"; "error" -> "Couldn't reach NS&I"; else -> "Waiting for the first draw check" },
                style = Hub.text(8.sp, if (e.state == "won") Hub.up else if (e.state == "error") Hub.down else Hub.ink2))
            e.num("won_this_year")?.takeIf { it > 0 }?.let { n -> Text(" · ${n.toInt()} prizes this year, ", style = Hub.text(8.sp, Hub.ink2)); Money(gbp(e.num("won_this_year_total")), show, Hub.text(8.sp, Hub.ink2)) }
        }
    }
}

@Composable
private fun Exposure(ex: JsonObject?, show: Boolean, all: Boolean = false) {
    val assets = ex?.list("asset")?.filter { (it.d("value") ?: 0.0) > 0 }?.sortedByDescending { it.d("value") } ?: return
    if (assets.isEmpty()) return
    val sum = assets.sumOf { it.d("value") ?: 0.0 }
    val regions = ex.list("regions")
    val shares = regions.sumOf { it.d("value") ?: 0.0 }
    @Composable fun bar(name: String, v: Double, total: Double, group: Int) {
        val p = if (total > 0) v / total * 100 else 0.0
        Row(Modifier.padding(vertical = 1.5.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(name, style = Hub.text(if (group == 2) 8.sp else 8.5.sp, if (group == 1) Hub.ink else Hub.ink2, if (group == 1) 600 else 400),
                modifier = Modifier.width(92.dp).padding(start = if (group == 2) 9.dp else 0.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Box(Modifier.weight(1f).height(5.dp).clip(RoundedCornerShape(4.dp)).background(Color.White.copy(alpha = .05f))) {
                Box(Modifier.fillMaxWidth((p / 100).toFloat().coerceAtLeast(.006f)).height(5.dp).background(Hub.ink.copy(alpha = if (group == 2) .32f else .62f)))
            }
            Text(if (p < 10) "%.1f%%".format(p) else "%.0f%%".format(p), style = Hub.text(8.sp, if (group == 2) Hub.ink2 else Hub.ink, 500, Hub.mono),
                modifier = Modifier.width(38.dp).padding(start = 6.dp))
            Money(gbp(v), show, Hub.text(7.5.sp, Hub.ink3, family = Hub.mono), Modifier.width(46.dp))
        }
    }
    Column(Modifier.padding(top = if (all) 0.dp else 12.dp)) {
        Row { Kicker("Asset class", modifier = Modifier.weight(1f)); Kicker("of everything") }
        Spacer(Modifier.height(4.dp))
        for (x in assets) bar(x.s("name").orEmpty(), x.d("value") ?: 0.0, sum, 0)
        if (regions.isNotEmpty()) {
            Row(Modifier.padding(top = 9.dp, bottom = 4.dp)) { Kicker("Shares by region", modifier = Modifier.weight(1f)); Kicker("of your shares") }
            val groups = regions.groupBy { it.s("group").orEmpty() }.map { (g, xs) -> g to xs }.sortedByDescending { (_, xs) -> xs.sumOf { it.d("value") ?: 0.0 } }
            for ((g, xs) in groups) {
                bar(g, xs.sumOf { it.d("value") ?: 0.0 }, shares, 1)
                for (r in xs.sortedByDescending { it.d("value") }.take(if (all) 99 else 2)) if ((r.d("value") ?: 0.0) / shares >= .01) bar(r.s("name").orEmpty(), r.d("value") ?: 0.0, shares, 2)
            }
        }
        val funds = ex.d("funds")?.toInt() ?: 0; val analysed = ex.d("analysed")?.toInt() ?: 0
        Text((if (analysed < funds) "$analysed of $funds funds analysed · " else "") + "from the funds' FT factsheets", style = Hub.text(7.5.sp, Hub.ink3), modifier = Modifier.padding(top = 6.dp))
    }
}

/** A wrapping row (enough for the legend; avoids pulling in the experimental FlowRow). */
@Composable
fun FlowRowSimple(modifier: Modifier = Modifier, gap: Dp = 10.dp, content: @Composable () -> Unit) =
    androidx.compose.ui.layout.Layout(content, modifier) { measurables, constraints ->
        val ps = measurables.map { it.measure(constraints.copy(minWidth = 0)) }
        val g = gap.roundToPx(); var x = 0; var y = 0; var lineH = 0
        val pos = ps.map { p -> if (x > 0 && x + p.width > constraints.maxWidth) { x = 0; y += lineH + g / 2; lineH = 0 }
            val at = x to y; x += p.width + g; lineH = maxOf(lineH, p.height); at }
        layout(constraints.maxWidth, y + lineH) { ps.forEachIndexed { i, p -> p.place(pos[i].first, pos[i].second) } }
    }

/** A holding, full screen over the home: its price chart with your average cost, returns and the position. */
@Composable
fun HoldingView(ctx: Ctx, sedol: String, onClose: () -> Unit) {
    val inv = ctx.s[Ids2.INVEST]?.attrs ?: return
    val h = inv.list("holdings").firstOrNull { it.s("sedol") == sedol } ?: return
    val context = LocalContext.current
    val show = Privacy.shown(context)
    var range by remember { mutableStateOf("1Y") }
    val all = seriesOf(ctx, sedol)
    val span = if (all.isEmpty()) 0 else all.last().first - all.first().first
    val pts = all.since(RANGES.getValue(range))
    val avg = (h.d("cost") ?: 0.0).let { c -> h.d("units")?.takeIf { it > 0 }?.let { c / it * 100 } }
    val stock = inv.list("holdings").sumOf { it.d("value") ?: 0.0 }.takeIf { it > 0 } ?: 1.0
    Box(Modifier.background(Color.Black.copy(alpha = .6f)).padding(horizontal = 120.dp, vertical = 40.dp)) {
        HubCard(padding = 24.dp) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Kicker("${h.s("stock_type") ?: "Fund"} · ${h.s("account").orEmpty()}", modifier = Modifier.weight(1f))
                Pressable(onClick = onClose, shape = CircleShape) { Text("Close", style = Hub.text(10.sp, Hub.ink2), modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp)) }
            }
            Text(h.s("name").orEmpty(), style = Hub.text(24.sp, family = Hub.serif))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(pence(h.d("price_p")), style = Hub.text(16.sp, weight = 500, family = Hub.mono))
                h.d("day_change_pct")?.let { Text("  ${pct(it, 2)} today", style = Hub.text(10.sp, upDown(it))) }
            }
            Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Kicker("Price, $range"); Text("  ${pct(pts.change())}", style = Hub.text(8.sp, upDown(pts.change()), 600)); Spacer(Modifier.weight(1f))
                RangeTabs(range, span) { range = it }
            }
            LineChart(pts, Modifier.fillMaxWidth().height(170.dp).padding(top = 8.dp), ref = avg)
            if (avg != null) Text("Dashed: your average cost, ${pence(avg)}", style = Hub.text(8.sp, Hub.ink3), modifier = Modifier.padding(top = 4.dp))
            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((k, d) in RANGES) if (span >= d * .8) {
                    val r = all.since(d).change()
                    Column(Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(Color.White.copy(alpha = .04f)).padding(7.dp)) {
                        Kicker(k); Text(pct(r), style = Hub.text(10.sp, upDown(r), 500, Hub.mono))
                    }
                }
            }
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                @Composable fun stat(label: String, value: String, money: Boolean = true, color: Color = Hub.ink) = Column(Modifier.weight(1f)
                    .clip(RoundedCornerShape(10.dp)).border(1.dp, Hub.line, RoundedCornerShape(10.dp)).padding(8.dp)) {
                    Kicker(label); if (money) Money(value, show, Hub.text(11.sp, color, 500, Hub.mono)) else Text(value, style = Hub.text(11.sp, color, 500, Hub.mono))
                }
                stat("Value", gbp(h.d("value"), 2)); stat("Gain", signed(h.d("gain")) { gbp(it, 2) }, color = upDown(h.d("gain")))
                stat("Cost", gbp(h.d("cost"), 2)); stat("Average cost", pence(avg), money = false)
                stat("Of portfolio", "%.1f%%".format((h.d("value") ?: 0.0) / stock * 100), money = false)
            }
            Text("Prices: Financial Times, daily close.", style = Hub.text(8.sp, Hub.ink3), modifier = Modifier.padding(top = 8.dp))
        }
    }
}

