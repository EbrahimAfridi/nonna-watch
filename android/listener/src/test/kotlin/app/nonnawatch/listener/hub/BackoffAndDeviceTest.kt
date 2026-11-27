package app.nonnawatch.listener.hub

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BackoffAndDeviceTest {

    @Test
    fun waitsDoubleUpToSixteenSecondsThenStayAtThirty() {
        assertEquals(
            listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L, 30_000L),
            (0..7).map { backoffMs(failures = it, jitter = 1.0) },
        )
    }

    @Test
    fun jitterMovesAWaitByUpToTwentyPercent() {
        assertEquals(24_000L, backoffMs(failures = 5, jitter = 0.8))
        assertEquals(36_000L, backoffMs(failures = 5, jitter = 1.2))
    }

    @Test
    fun randomJitterStaysWithinTwentyPercent() {
        repeat(10_000) {
            val jitter = randomJitter()
            assertTrue("jitter $jitter", jitter >= 0.8 && jitter < 1.2)
        }
    }

    @Test
    fun theDeviceNameIsMakerAndModel() {
        assertEquals("Nothing A001", deviceModel("Nothing", "A001"))
        assertEquals("Google sdk_gphone64_x86_64", deviceModel("Google", "sdk_gphone64_x86_64"))
    }

    @Test
    fun theMakerIsNotRepeatedWhenTheModelAlreadySaysIt() {
        assertEquals("Xiaomi 13T", deviceModel("Xiaomi", "Xiaomi 13T"))
        assertEquals("Samsung Galaxy A54", deviceModel("samsung", "Samsung Galaxy A54"))
    }

    @Test
    fun theHubGetsOnlyPrintableAsciiOfAtMostEightyCharacters() {
        assertEquals("Pixel? 7 ?", printableAscii("Pixel™ 7 é"))
        assertEquals(80, printableAscii("x".repeat(200)).length)
    }
}
