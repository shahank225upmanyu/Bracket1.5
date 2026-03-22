package com.braket.positioning.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import com.braket.positioning.network.Config
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Reads Accelerometer, Gyroscope, and Magnetometer from the hardware.
 *
 * Exposes [SensorReadings] as a [StateFlow] so the network layer can
 * sample it at the desired transmission rate without blocking.
 *
 * Step detection is built-in using a simple peak-detection algorithm on
 * the accelerometer magnitude, suitable for pedestrian dead reckoning (PDR).
 */
class SensorHub(context: Context) : SensorEventListener {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val _readings = MutableStateFlow(SensorReadings())
    val readings: StateFlow<SensorReadings> = _readings

    // Step detection state
    private var lastMagnitude = 0f
    private var stepCount = 0
    private var lastStepTime = 0L
    private val STEP_THRESHOLD = 11.5f          // m/s² magnitude threshold
    private val STEP_MIN_INTERVAL_MS = 250L     // minimum 250 ms between steps

    // Low-pass filter state for magnetometer
    private var magFiltered = FloatArray(3)

    fun start() {
        val rate = Config.SENSOR_SAMPLE_RATE_US

        listOf(
            Sensor.TYPE_ACCELEROMETER,
            Sensor.TYPE_GYROSCOPE,
            Sensor.TYPE_MAGNETIC_FIELD,
            Sensor.TYPE_ROTATION_VECTOR       // fused orientation from OS
        ).forEach { type ->
            sensorManager.getDefaultSensor(type)?.let { sensor ->
                sensorManager.registerListener(this, sensor, rate)
            }
        }
    }

    fun stop() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        val current = _readings.value
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                val ax = event.values[0]
                val ay = event.values[1]
                val az = event.values[2]
                val magnitude = Math.sqrt((ax * ax + ay * ay + az * az).toDouble()).toFloat()

                // Peak detection step counter
                val now = System.currentTimeMillis()
                if (magnitude > STEP_THRESHOLD && lastMagnitude <= STEP_THRESHOLD
                    && now - lastStepTime > STEP_MIN_INTERVAL_MS) {
                    stepCount++
                    lastStepTime = now
                }
                lastMagnitude = magnitude

                _readings.value = current.copy(
                    ax = ax, ay = ay, az = az,
                    accelMagnitude = magnitude,
                    stepCount = stepCount
                )
            }

            Sensor.TYPE_GYROSCOPE -> {
                _readings.value = current.copy(
                    gx = event.values[0],
                    gy = event.values[1],
                    gz = event.values[2]
                )
            }

            Sensor.TYPE_MAGNETIC_FIELD -> {
                // Low-pass filter alpha = 0.15 — reduces device jitter
                val alpha = 0.15f
                magFiltered[0] = alpha * event.values[0] + (1 - alpha) * magFiltered[0]
                magFiltered[1] = alpha * event.values[1] + (1 - alpha) * magFiltered[1]
                magFiltered[2] = alpha * event.values[2] + (1 - alpha) * magFiltered[2]
                val magnitude = Math.sqrt(
                    (magFiltered[0] * magFiltered[0] +
                     magFiltered[1] * magFiltered[1] +
                     magFiltered[2] * magFiltered[2]).toDouble()
                ).toFloat()
                _readings.value = current.copy(
                    bx = magFiltered[0], by = magFiltered[1], bz = magFiltered[2],
                    magMagnitude = magnitude
                )
            }

            Sensor.TYPE_ROTATION_VECTOR -> {
                // Convert rotation vector to azimuth (heading) in degrees
                val rotMatrix = FloatArray(9)
                val orientation = FloatArray(3)
                SensorManager.getRotationMatrixFromVector(rotMatrix, event.values)
                SensorManager.getOrientation(rotMatrix, orientation)
                val heading = Math.toDegrees(orientation[0].toDouble()).toFloat()
                _readings.value = current.copy(headingDeg = heading)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) { /* no-op */ }
}

data class SensorReadings(
    // Accelerometer (m/s²)
    val ax: Float = 0f,
    val ay: Float = 0f,
    val az: Float = 0f,
    val accelMagnitude: Float = 0f,
    val stepCount: Int = 0,

    // Gyroscope (rad/s)
    val gx: Float = 0f,
    val gy: Float = 0f,
    val gz: Float = 0f,

    // Magnetometer (µT, low-pass filtered)
    val bx: Float = 0f,
    val by: Float = 0f,
    val bz: Float = 0f,
    val magMagnitude: Float = 0f,

    // Fused heading from OS rotation vector (degrees)
    val headingDeg: Float = 0f,

    // Timestamp
    val timestampMs: Long = System.currentTimeMillis()
)
