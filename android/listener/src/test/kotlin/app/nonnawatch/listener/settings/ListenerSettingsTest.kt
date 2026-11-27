package app.nonnawatch.listener.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ListenerSettingsTest {

    @Test
    fun anAddressAndATokenAreEnough() {
        assertNull(ListenerSettings("ws://192.168.43.12:8000/ws/listener", "abc").problem())
        assertNull(ListenerSettings("wss://nonna-hub-xyz.a.run.app/ws/listener", "abc").problem())
    }

    @Test
    fun spacesFromAPasteDoNotCount() {
        val pasted = ListenerSettings("  ws://10.0.2.2:8000/ws/listener\n", " abc \n")

        assertNull(pasted.problem())
        assertEquals("ws://10.0.2.2:8000/ws/listener", pasted.cleaned().hubUrl)
        assertEquals("abc", pasted.cleaned().token)
    }

    @Test
    fun aMissingAddressIsExplained() {
        assertEquals(
            "enter the hub address the hub printed, like ws://192.168.43.12:8000/ws/listener",
            ListenerSettings(hubUrl = " ", token = "abc").problem(),
        )
    }

    @Test
    fun anAddressThatIsNotAWebSocketIsExplained() {
        val wrong = listOf(
            "http://192.168.43.12:8000/ws/listener",
            "192.168.43.12:8000",
            "ws://",
            "ws://bad address",
        )
        for (url in wrong) {
            assertEquals(
                url,
                "the hub address must look like ws://192.168.43.12:8000/ws/listener",
                ListenerSettings(hubUrl = url, token = "abc").problem(),
            )
        }
    }

    @Test
    fun aMissingTokenIsExplained() {
        assertEquals(
            "enter the token (HUB_TOKEN in the hub's .env file)",
            ListenerSettings(hubUrl = "ws://10.0.2.2:8000/ws/listener", token = "").problem(),
        )
    }
}
