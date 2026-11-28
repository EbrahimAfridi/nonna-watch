package app.nonnawatch.listener.light

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/**
 * The phone's light sensor (the one next to the screen, for auto-brightness) as lux readings, or
 * null when the phone has none. The sensor runs only while the flow is collected.
 *
 * It needs no permission. Android 9+ gives sensor readings to an app in the background only from
 * a foreground service, which is where the listener reads it.
 */
fun lightReadings(context: Context): Flow<Float>? {
    val sensors = context.getSystemService(SensorManager::class.java) ?: return null
    val sensor = sensors.getDefaultSensor(Sensor.TYPE_LIGHT) ?: return null
    return callbackFlow {
        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                trySend(event.values[0])
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        // A light sensor reports only when the light changes, and once right after it starts.
        if (!sensors.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_NORMAL)) {
            close() // the screen then says there is no light sensor
        }
        awaitClose { sensors.unregisterListener(listener) }
    }
}
