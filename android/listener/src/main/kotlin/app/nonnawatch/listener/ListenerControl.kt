package app.nonnawatch.listener

import android.content.Context
import app.nonnawatch.listener.voice.AskResult
import app.nonnawatch.listener.voice.QuestionLanguage
import app.nonnawatch.listener.voice.androidCheckInQuestion
import kotlinx.coroutines.flow.StateFlow

/**
 * What the screen needs from the listening service. It is an interface so the ViewModel tests can
 * use a fake one and run on the PC, without a phone.
 */
interface ListenerControl {
    val state: StateFlow<ServiceState>

    /**
     * Starts listening with the settings last saved. Only call this while the app is on screen:
     * Android lets only a visible app turn on the microphone.
     */
    fun start()

    fun stop()

    fun setPaused(paused: Boolean)

    /**
     * Speaks the check-in question in [language] with the phone's own voice, as an alarm, and
     * returns how it went. Works without a hub and while not listening.
     */
    suspend fun testQuestion(language: QuestionLanguage): AskResult
}

/** The real one: starts and stops [ListenerService]. */
class ServiceListenerControl(context: Context) : ListenerControl {
    // The application context, so a ViewModel holding this never keeps a closed screen in memory.
    private val context = context.applicationContext

    override val state: StateFlow<ServiceState> = ServiceStateHolder.state

    override fun start() = ListenerService.start(context)

    override fun stop() = ListenerService.stop(context)

    override fun setPaused(paused: Boolean) {
        ServiceStateHolder.paused.value = paused
    }

    override suspend fun testQuestion(language: QuestionLanguage): AskResult =
        androidCheckInQuestion(context, speechFileName = "test_question.wav")
            .test(language.text, language.tag)
}
