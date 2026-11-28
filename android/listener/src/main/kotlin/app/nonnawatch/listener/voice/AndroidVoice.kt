package app.nonnawatch.listener.voice

import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import kotlin.coroutines.resume
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * The check-in question with Android's text-to-speech and media player. [speechFileName] is the
 * file in the cache folder that holds the phone's voice while it plays; the listening service and
 * the Test button use different ones, so they never share a file.
 */
fun androidCheckInQuestion(context: Context, speechFileName: String, log: (String) -> Unit = {}): CheckInQuestion {
    val app = context.applicationContext
    return CheckInQuestion(
        clips = ClipStore(File(app.filesDir, "voice_check")),
        speech = TextToSpeechSpeech(app),
        player = MediaAlarmPlayer(),
        alarmAudible = { alarmAudible(app) },
        speechFile = File(app.cacheDir, speechFileName),
        log = log,
    )
}

/** Alarms play when the phone is on silent or vibrate, so the question is heard (docs/api-contract.md). */
private val ALARM_SPEECH: AudioAttributes = AudioAttributes.Builder()
    .setUsage(AudioAttributes.USAGE_ALARM)
    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
    .build()

/** False when an alarm would be silent: the alarm volume is at zero, or Do Not Disturb is set to total silence. */
private fun alarmAudible(context: Context): Boolean {
    val audio = context.getSystemService(AudioManager::class.java) ?: return false
    val totalSilence = context.getSystemService(NotificationManager::class.java)
        ?.currentInterruptionFilter == NotificationManager.INTERRUPTION_FILTER_NONE
    return audio.getStreamVolume(AudioManager.STREAM_ALARM) > 0 && !totalSilence
}

/**
 * The phone's text-to-speech. The voice app starts for each question and stops after it: questions
 * are rare, and a voice app kept running would hold memory all day.
 */
class TextToSpeechSpeech(private val context: Context) : Speech {

    override suspend fun write(text: String, lang: String, into: File): String? {
        val engine = startEngine() ?: return NotPlayedReason.NO_TEXT_TO_SPEECH
        try {
            // Below zero is LANG_MISSING_DATA (voice not downloaded) or LANG_NOT_SUPPORTED.
            if (engine.setLanguage(Locale.forLanguageTag(lang)) < 0) {
                return NotPlayedReason.NO_VOICE_FOR_LANGUAGE
            }
            return writeSpeech(engine, text, into)
        } finally {
            engine.shutdown()
        }
    }

    /** The engine once it is ready, or null when the phone has none or it would not start. */
    private suspend fun startEngine(): TextToSpeech? {
        val status = CompletableDeferred<Int>()
        val engine = TextToSpeech(context) { status.complete(it) }
        val ready = try {
            status.await() == TextToSpeech.SUCCESS
        } catch (e: CancellationException) {
            engine.shutdown()
            throw e
        }
        if (!ready) engine.shutdown()
        return engine.takeIf { ready }
    }

    private suspend fun writeSpeech(engine: TextToSpeech, text: String, into: File): String? {
        val finished = CompletableDeferred<Boolean>()
        engine.setOnUtteranceProgressListener(
            object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = Unit

                override fun onDone(utteranceId: String?) {
                    finished.complete(true)
                }

                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) {
                    finished.complete(false)
                }

                override fun onError(utteranceId: String?, errorCode: Int) {
                    finished.complete(false)
                }
            },
        )
        into.delete()
        if (engine.synthesizeToFile(text, Bundle(), into, UTTERANCE_ID) != TextToSpeech.SUCCESS) {
            return NotPlayedReason.TEXT_TO_SPEECH_FAILED
        }
        return if (finished.await() && into.length() > 0) null else NotPlayedReason.TEXT_TO_SPEECH_FAILED
    }

    private companion object {
        const val UTTERANCE_ID = "check-in-question"
    }
}

/**
 * Plays a file with Android's MediaPlayer, as an alarm. Create it on the main thread: MediaPlayer
 * reports back on the thread it was made on.
 */
class MediaAlarmPlayer(private val clock: () -> Long = System::currentTimeMillis) : AlarmPlayer {

    override suspend fun play(file: File): AskResult {
        val player = MediaPlayer()
        try {
            player.setAudioAttributes(ALARM_SPEECH)
            player.setDataSource(file.path)
            return suspendCancellableCoroutine { waiting ->
                var startedMs = 0L
                player.setOnPreparedListener {
                    it.start()
                    startedMs = clock()
                }
                player.setOnCompletionListener {
                    if (waiting.isActive) waiting.resume(AskResult.Played(startedMs, endedMs = clock()))
                }
                player.setOnErrorListener { _, _, _ ->
                    if (waiting.isActive) waiting.resume(AskResult.NotPlayed(NotPlayedReason.PLAYBACK_FAILED))
                    true
                }
                player.prepareAsync()
            }
        } catch (e: CancellationException) {
            throw e // stopped; release() below stops the sound
        } catch (e: Exception) {
            // A file MediaPlayer cannot read (IOException), or MediaPlayer in a wrong state.
            return AskResult.NotPlayed(NotPlayedReason.PLAYBACK_FAILED)
        } finally {
            player.release()
        }
    }
}
