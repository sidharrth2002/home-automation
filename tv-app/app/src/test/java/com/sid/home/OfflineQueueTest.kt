package com.sid.home

import com.sid.home.ha.Entity
import com.sid.home.ha.HomeState
import com.sid.home.ha.OfflineQueue
import com.sid.home.ha.data
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** What happens to presses while Home Assistant can't be reached. */
class OfflineQueueTest {
    private var now = 1_000_000L
    private val home = HomeState().apply {
        replace(listOf(Entity("input_boolean.guest_photos", "off"), Entity("light.desk_lamp", "on"),
            Entity("input_select.music_sync_mode", "party")).associateBy { it.id })
    }
    private val queue = OfflineQueue(home) { now }

    @Test fun toggleIsStoredAsTheStateItLedTo() {
        assertTrue(queue.add("input_boolean", "toggle", data("entity_id" to "input_boolean.guest_photos")))
        assertEquals("on", home.entities.value["input_boolean.guest_photos"]!!.state) // shown at once
        assertEquals(listOf(Triple("input_boolean", "turn_on", data("entity_id" to "input_boolean.guest_photos"))), queue.drain())
    }

    @Test fun twoTogglesCancelOutRatherThanFlipTwiceLater() {
        queue.add("input_boolean", "toggle", data("entity_id" to "input_boolean.guest_photos"))
        queue.add("input_boolean", "toggle", data("entity_id" to "input_boolean.guest_photos"))
        assertEquals("off", home.entities.value["input_boolean.guest_photos"]!!.state)
        assertEquals("turn_off", queue.drain().single().second) // one call, the final wish
    }

    @Test fun onlyTheLatestValueIsKept() {
        queue.add("input_select", "select_option", data("entity_id" to "input_select.music_sync_mode", "option" to "calm"))
        queue.add("input_select", "select_option", data("entity_id" to "input_select.music_sync_mode", "option" to "tv"))
        assertEquals("tv", home.entities.value["input_select.music_sync_mode"]!!.state)
        assertEquals("tv", queue.drain().single().third["option"].toString().trim('"'))
        assertEquals(0, home.pending.value)
    }

    @Test fun oneOffActionsAreNotQueued() {
        assertFalse(queue.add("script", "turn_on", data("entity_id" to "script.party_mode")))
        assertFalse(queue.add("remote", "send_command", data("entity_id" to "remote.tv", "command" to "HOME")))
        assertTrue(queue.drain().isEmpty())
    }

    @Test fun staleChangesAreDropped() {
        queue.add("light", "turn_off", data("entity_id" to "light.desk_lamp"))
        now += OfflineQueue.MAX_AGE_MS + 1
        assertTrue(queue.drain().isEmpty()) // nothing switching on (or off) hours later
    }
}
