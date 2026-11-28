package app.nonnawatch.listener.voice

import java.io.File
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ClipStoreTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val dir by lazy { File(folder.root, "voice_check") }

    @Test
    fun thereIsNoRecordingUntilTheFamilySendsOne() {
        assertNull(ClipStore(dir).current())
    }

    @Test
    fun aNewRecordingReplacesTheOldOne() {
        val store = ClipStore(dir)

        store.save(byteArrayOf(1, 1))
        store.save(byteArrayOf(2, 2, 2))

        assertArrayEquals(byteArrayOf(2, 2, 2), store.current()?.readBytes())
        assertEquals(listOf("checkin_clip"), dir.list()?.toList()) // no half-written file left over
    }

    @Test
    fun theRecordingIsStillThereAfterARestart() {
        ClipStore(dir).save(byteArrayOf(7))

        assertArrayEquals(byteArrayOf(7), ClipStore(dir).current()?.readBytes())
    }

    @Test
    fun deletingLeavesNoRecording() {
        val store = ClipStore(dir)
        store.save(byteArrayOf(1))

        store.delete()
        store.delete() // deleting twice is fine

        assertNull(store.current())
    }
}
