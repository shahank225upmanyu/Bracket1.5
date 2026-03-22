package com.braket.positioning.fusion

import com.braket.positioning.sensor.SensorReadings
import kotlin.math.cos
import kotlin.math.sin

/**
 * Pedestrian Dead Reckoning (PDR) running on the TARGET phone.
 *
 * Integrates step events + heading to estimate displacement between
 * BLE position fixes. This is sent to the server so the EKF can use it
 * as a prediction step at 10 Hz instead of waiting for the next BLE fix.
 *
 * Stride length estimation:
 *   Base stride 0.7 m, scaled by sqrt(accel_magnitude / gravity) — this
 *   approximates how hard the step is to estimate step length.
 */
class PdrTracker {

    private var lastStepCount = 0
    private var lastHeadingDeg = 0f

    // Accumulated displacement since last reset
    private var dxTotal = 0.0
    private var dyTotal = 0.0

    private val BASE_STRIDE_M = 0.70
    private val GRAVITY = 9.81

    /**
     * Feed the latest sensor readings.
     * Returns [PdrDelta] if a new step was detected, null otherwise.
     */
    fun update(readings: SensorReadings): PdrDelta? {
        val newSteps = readings.stepCount - lastStepCount
        if (newSteps <= 0) return null

        lastStepCount = readings.stepCount

        // Stride length scales with acceleration magnitude
        val strideM = BASE_STRIDE_M * Math.sqrt(
            (readings.accelMagnitude / GRAVITY).coerceIn(0.5, 2.0)
        )
        val distanceM = strideM * newSteps

        // Heading from fused rotation vector (degrees → radians, 0 = North/+Y)
        val headingRad = Math.toRadians(readings.headingDeg.toDouble())
        lastHeadingDeg = readings.headingDeg

        val dx = distanceM * sin(headingRad)
        val dy = distanceM * cos(headingRad)

        dxTotal += dx
        dyTotal += dy

        return PdrDelta(
            steps = newSteps,
            headingDeg = readings.headingDeg,
            strideM = strideM,
            dx = dx,
            dy = dy,
            dxTotal = dxTotal,
            dyTotal = dyTotal
        )
    }

    fun reset() {
        dxTotal = 0.0
        dyTotal = 0.0
        lastStepCount = 0
    }
}

data class PdrDelta(
    val steps: Int,
    val headingDeg: Float,
    val strideM: Double,
    val dx: Double,         // displacement east (m)
    val dy: Double,         // displacement north (m)
    val dxTotal: Double,    // accumulated since last reset
    val dyTotal: Double
)
