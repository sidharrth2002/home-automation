package com.sid.home.ui

import androidx.compose.runtime.MutableState
import androidx.compose.runtime.Stable
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.staticCompositionLocalOf
import com.sid.home.ha.Entity

/**
 * The entities as the screens read them: a Map with one snapshot state per entity, so a card recomposes only when an
 * entity it read changes. (One state for the whole map rebuilt every card on the page for any change in the house:
 * during music sync the lamps change several times a second, and the rail stuttered.) [update] runs on the main thread.
 */
@Stable
class LiveEntities : AbstractMap<String, Entity>() {
    private val slots = HashMap<String, MutableState<Entity?>>()
    private var current: Map<String, Entity> = emptyMap()
    /** Bumped when entities come or go (keys, size), and on any change (iterating every value). */
    private val keysVersion = mutableIntStateOf(0)
    private val anyVersion = mutableIntStateOf(0)

    fun update(next: Map<String, Entity>) {
        val prev = current
        if (next === prev) return
        current = next
        var changed = false
        // unchanged entities keep their instance in HomeState's map, so the reference check skips nearly all of them
        for ((id, e) in next) {
            val old = prev[id]
            if (old !== e && old != e) { changed = true; slots[id]?.value = e }
        }
        var keys = prev.size != next.size
        for (id in prev.keys) if (id !in next) { keys = true; changed = true; slots[id]?.value = null }
        if (keys) keysVersion.intValue++
        if (changed) anyVersion.intValue++
    }

    override fun get(key: String): Entity? = slots.getOrPut(key) { mutableStateOf(current[key]) }.value
    override fun containsKey(key: String) = get(key) != null
    override val size: Int get() { keysVersion.intValue; return current.size }
    override val keys: Set<String> get() { keysVersion.intValue; return current.keys }
    override val entries: Set<Map.Entry<String, Entity>> get() { anyVersion.intValue; return current.entries }
}

/**
 * True while something opaque covers the home screen (the screensaver): the always-moving parts (the ambient glow, the
 * Music page's light) stop asking for frames underneath it.
 */
val LocalCovered = staticCompositionLocalOf<State<Boolean>> { mutableStateOf(false) }
