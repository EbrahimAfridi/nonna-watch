package app.nonnawatch.listener.voice

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * The family's recorded check-in question, kept in this app's private files so it is still there
 * after a restart. The hub sends it to be kept (`checkin_clip` in docs/api-contract.md). It is the
 * family's message, not sound from the home: that is never saved.
 *
 * The calls read and write the disk, so call them off the main thread.
 */
class ClipStore(private val dir: File) {
    private val clip = File(dir, "checkin_clip")

    /**
     * Replaces the saved recording. The new one is written next to it and then swapped in, so a
     * question playing at that moment never gets half a file.
     */
    fun save(audio: ByteArray) {
        dir.mkdirs()
        val next = File(dir, "checkin_clip.new")
        next.writeBytes(audio)
        Files.move(next.toPath(), clip.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }

    fun delete() {
        clip.delete()
    }

    /** The saved recording, or null when the family has none. */
    fun current(): File? = clip.takeIf { it.isFile }
}
