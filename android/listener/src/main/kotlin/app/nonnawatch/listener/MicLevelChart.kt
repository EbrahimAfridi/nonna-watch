package app.nonnawatch.listener

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

/**
 * The last minute of sound as bars drawn on a Canvas, one per second, newest on the right and
 * taller when louder. [levels] are 0 to 1, oldest first (MicState.Recording.levels).
 */
@Composable
fun MicLevelChart(levels: List<Float>, modifier: Modifier = Modifier) {
    val background = MaterialTheme.colorScheme.surfaceVariant
    val barColor = MaterialTheme.colorScheme.primary
    val now = levels.lastOrNull()
    val description = if (now == null) {
        "Sound level: waiting for the first second"
    } else {
        "Sound level of the last minute; now ${(now * 100).roundToInt()} %"
    }

    Canvas(modifier.fillMaxWidth().height(64.dp), contentDescription = description) {
        drawRoundRect(background, cornerRadius = CornerRadius(8.dp.toPx()))
        val padding = 6.dp.toPx()
        val bars = levelBars(
            levels = levels,
            slots = LEVEL_SECONDS,
            width = size.width - 2 * padding,
            height = size.height - 2 * padding,
            minHeight = 2.dp.toPx(),
        )
        for (bar in bars) {
            drawRect(
                barColor,
                topLeft = Offset(padding + bar.left, padding + bar.top),
                size = Size(bar.width, bar.height),
            )
        }
    }
}

/** One bar of the level drawing, in pixels from the top left of the drawing area. */
internal data class Bar(val left: Float, val top: Float, val width: Float, val height: Float)

/**
 * Where each bar goes in a [width] × [height] area split into [slots] places, one per second:
 * the newest on the right, filling in from the right until a minute has been heard. Bars stand on
 * the bottom edge. A silent second still gets a bar [minHeight] tall, so a working microphone in
 * a silent room is a thin line, not an empty box.
 */
internal fun levelBars(levels: List<Float>, slots: Int, width: Float, height: Float, minHeight: Float): List<Bar> {
    if (slots <= 0 || width <= 0f || height <= 0f) return emptyList()
    val slotWidth = width / slots
    val barWidth = slotWidth * BAR_SHARE
    val shown = levels.takeLast(slots)
    val firstSlot = slots - shown.size
    val lowest = minHeight.coerceIn(0f, height)
    return shown.mapIndexed { index, level ->
        val barHeight = (level.coerceIn(0f, 1f) * height).coerceAtLeast(lowest)
        Bar(
            left = (firstSlot + index) * slotWidth + (slotWidth - barWidth) / 2,
            top = height - barHeight,
            width = barWidth,
            height = barHeight,
        )
    }
}

/** Each bar takes 70 % of its place; the rest is the gap to the next bar. */
private const val BAR_SHARE = 0.7f
