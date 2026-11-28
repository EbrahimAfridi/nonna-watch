package app.nonnawatch.listener.settings

import android.content.Context
import androidx.core.content.edit
import app.nonnawatch.core.Room
import java.net.URI
import java.net.URISyntaxException
import java.util.UUID

/** What the person sets up once on each listener phone. */
data class ListenerSettings(
    /** As the hub prints it on start, for example ws://192.168.43.12:8000/ws/listener. */
    val hubUrl: String = "",
    /** HUB_TOKEN from the hub's .env. A secret: kept on this phone only, never logged. */
    val token: String = "",
    val room: Room = Room.KITCHEN,
) {
    /** Without the spaces a paste can bring along. */
    fun cleaned() = copy(hubUrl = hubUrl.trim(), token = token.trim())

    /** What is missing before the phone can connect, in words for the screen; null when ready. */
    fun problem(): String? {
        val clean = cleaned()
        return when {
            clean.hubUrl.isEmpty() ->
                "enter the hub address the hub printed, like ws://192.168.43.12:8000/ws/listener"
            !isHubUrl(clean.hubUrl) ->
                "the hub address must look like ws://192.168.43.12:8000/ws/listener"
            clean.token.isEmpty() -> "enter the token (HUB_TOKEN in the hub's .env file)"
            else -> null
        }
    }
}

/** Where the settings are kept. An interface so the ViewModel tests can use a fake one. */
interface SettingsStore {
    fun load(): ListenerSettings

    fun save(settings: ListenerSettings)

    /** A random id made on first use and then kept: `device_id` in hello. Not a hardware id. */
    fun deviceId(): String
}

/**
 * The settings in the app's private storage on this phone. Other apps cannot read it, and it is
 * not backed up (allowBackup is false in the manifest).
 */
class PrefsSettingsStore(context: Context) : SettingsStore {
    private val prefs = context.applicationContext.getSharedPreferences("listener", Context.MODE_PRIVATE)

    override fun load() = ListenerSettings(
        hubUrl = prefs.getString(KEY_HUB_URL, null).orEmpty(),
        token = prefs.getString(KEY_TOKEN, null).orEmpty(),
        room = Room.fromId(prefs.getString(KEY_ROOM, null).orEmpty()) ?: Room.KITCHEN,
    )

    override fun save(settings: ListenerSettings) {
        prefs.edit {
            putString(KEY_HUB_URL, settings.hubUrl)
            putString(KEY_TOKEN, settings.token)
            putString(KEY_ROOM, settings.room.id)
        }
    }

    override fun deviceId(): String =
        prefs.getString(KEY_DEVICE_ID, null)
            ?: UUID.randomUUID().toString().also { prefs.edit { putString(KEY_DEVICE_ID, it) } }

    private companion object {
        const val KEY_HUB_URL = "hub_url"
        const val KEY_TOKEN = "token"
        const val KEY_ROOM = "room"
        const val KEY_DEVICE_ID = "device_id"
    }
}

/** ws:// or wss:// with a host. */
internal fun isHubUrl(text: String): Boolean = try {
    val uri = URI(text)
    (uri.scheme == "ws" || uri.scheme == "wss") && !uri.host.isNullOrEmpty()
} catch (e: URISyntaxException) {
    false
}
