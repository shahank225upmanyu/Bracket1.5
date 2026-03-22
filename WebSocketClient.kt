package com.braket.positioning.network

import android.util.Log
import com.braket.positioning.security.PacketSigner
import com.braket.positioning.sensor.SensorReadings
import com.braket.positioning.target.BleReading
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Maintains a persistent WebSocket connection to the FastAPI server.
 * Streams signed JSON payloads at [Config.WS_SEND_INTERVAL_MS].
 *
 * Auto-reconnects on disconnect with exponential back-off (max 30 s).
 *
 * JSON contract:
 * {
 *   "ts": <unix_ms>,
 *   "device_id": "<MAC or UUID>",
 *   "anchors": [{"id": "BRAKET-A", "rssi": -65, "tx_power": -59, "dist_m": 2.1}, ...],
 *   "imu": {"ax":…, "ay":…, "az":…, "gx":…, "gy":…, "gz":…, "steps":…, "heading":…},
 *   "mag": {"bx":…, "by":…, "bz":…, "mag":…},
 *   "pdr": {"dx":…, "dy":…, "heading":…, "steps":…},
 *   "sig": "<HMAC-SHA256 of payload without sig field>"
 * }
 */
class WebSocketClient(
    private val deviceId: String,
    private val scope: CoroutineScope
) {

    private val TAG = "WSClient"
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)   // WebSocket — no read timeout
        .pingInterval(Config.WS_PING_INTERVAL_MS, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var reconnectDelayMs = Config.WS_RECONNECT_DELAY_MS

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState

    private val listener = object : WebSocketListener() {
        override fun onOpen(ws: WebSocket, response: Response) {
            Log.i(TAG, "WebSocket connected")
            _connectionState.value = ConnectionState.CONNECTED
            reconnectDelayMs = Config.WS_RECONNECT_DELAY_MS  // reset back-off
        }
        override fun onMessage(ws: WebSocket, text: String) {
            handleServerMessage(text)
        }
        override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
            Log.e(TAG, "WebSocket failure: ${t.message}")
            _connectionState.value = ConnectionState.DISCONNECTED
            scheduleReconnect()
        }
        override fun onClosed(ws: WebSocket, code: Int, reason: String) {
            Log.i(TAG, "WebSocket closed: $code $reason")
            _connectionState.value = ConnectionState.DISCONNECTED
            if (code != 1000) scheduleReconnect()  // 1000 = normal closure
        }
    }

    fun connect() {
        _connectionState.value = ConnectionState.CONNECTING
        val request = Request.Builder().url(Config.WS_URL).build()
        webSocket = client.newWebSocket(request, listener)
    }

    fun disconnect() {
        reconnectJob?.cancel()
        webSocket?.close(1000, "User disconnected")
        webSocket = null
        _connectionState.value = ConnectionState.DISCONNECTED
    }

    /**
     * Builds and sends a signed JSON payload.
     * Call this at ~10 Hz from a coroutine loop.
     */
    fun send(
        bleReadings: List<BleReading>,
        sensors: SensorReadings,
        pdrDx: Double = 0.0,
        pdrDy: Double = 0.0
    ): Boolean {
        val ws = webSocket ?: return false
        if (_connectionState.value != ConnectionState.CONNECTED) return false

        // Build anchors array
        val anchorsArr = JSONArray().apply {
            bleReadings.forEach { r ->
                put(JSONObject().apply {
                    put("id", r.anchorId)
                    put("rssi", r.rssi)
                    put("tx_power", r.txPower)
                    put("dist_m", String.format("%.3f", r.distanceMeters()).toDouble())
                })
            }
        }

        // Build IMU object
        val imuObj = JSONObject().apply {
            put("ax", sensors.ax); put("ay", sensors.ay); put("az", sensors.az)
            put("gx", sensors.gx); put("gy", sensors.gy); put("gz", sensors.gz)
            put("steps", sensors.stepCount)
            put("heading", sensors.headingDeg)
        }

        // Build magnetometer object
        val magObj = JSONObject().apply {
            put("bx", sensors.bx); put("by", sensors.by); put("bz", sensors.bz)
            put("mag", sensors.magMagnitude)
        }

        // Build PDR object
        val pdrObj = JSONObject().apply {
            put("dx", pdrDx); put("dy", pdrDy)
            put("heading", sensors.headingDeg)
            put("steps", sensors.stepCount)
        }

        // Assemble payload (no sig yet)
        val payload = JSONObject().apply {
            put("ts", System.currentTimeMillis())
            put("device_id", deviceId)
            put("anchors", anchorsArr)
            put("imu", imuObj)
            put("mag", magObj)
            put("pdr", pdrObj)
        }

        // Sign the payload string, then attach signature
        val payloadStr = payload.toString()
        val sig = PacketSigner.sign(payloadStr)
        payload.put("sig", sig)

        return ws.send(payload.toString())
    }

    private fun scheduleReconnect() {
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            Log.i(TAG, "Reconnecting in ${reconnectDelayMs}ms…")
            delay(reconnectDelayMs)
            reconnectDelayMs = (reconnectDelayMs * 2).coerceAtMost(30_000L)
            connect()
        }
    }

    private fun handleServerMessage(text: String) {
        // Server can push position fixes or alerts back to the phone
        try {
            val obj = JSONObject(text)
            val type = obj.optString("type")
            when (type) {
                "position" -> {
                    val x = obj.getDouble("x")
                    val y = obj.getDouble("y")
                    val acc = obj.getDouble("accuracy_m")
                    Log.d(TAG, "Server position: x=%.2f y=%.2f acc=%.2fm".format(x, y, acc))
                }
                "alert" -> Log.w(TAG, "Security alert from server: ${obj.optString("reason")}")
                else -> Log.d(TAG, "Server msg: $text")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not parse server message: ${e.message}")
        }
    }

    enum class ConnectionState { DISCONNECTED, CONNECTING, CONNECTED }
}
