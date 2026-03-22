package com.braket.positioning.network

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.provider.Settings
import androidx.core.app.NotificationCompat
import com.braket.positioning.fusion.PdrTracker
import com.braket.positioning.sensor.SensorHub
import com.braket.positioning.target.BleScanner
import kotlinx.coroutines.*

/**
 * Foreground service that keeps BLE scanning, IMU reading, and WebSocket
 * streaming alive even when the app is backgrounded.
 *
 * Android kills background BLE scans after ~30 s. Running in foreground
 * with a persistent notification prevents this.
 *
 * Start via: startForegroundService(Intent(context, BeaconForegroundService::class.java))
 */
class BeaconForegroundService : Service() {

    private val CHANNEL_ID = "braket_scanning"
    private val NOTIFICATION_ID = 1001

    private lateinit var sensorHub: SensorHub
    private lateinit var bleScanner: BleScanner
    private lateinit var wsClient: WebSocketClient
    private lateinit var pdrTracker: PdrTracker
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var streamJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Initializing…"))

        val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
            ?: "unknown-device"

        sensorHub = SensorHub(this)
        bleScanner = BleScanner(this)
        wsClient = WebSocketClient(deviceId, serviceScope)
        pdrTracker = PdrTracker()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startStreaming()
            ACTION_STOP  -> stopStreaming()
        }
        return START_STICKY  // restart if killed by OS
    }

    private fun startStreaming() {
        sensorHub.start()
        bleScanner.start()
        wsClient.connect()

        streamJob = serviceScope.launch {
            // Give WS a moment to connect
            delay(1_000)
            while (isActive) {
                val bleReadings = bleScanner.getFreshReadings()
                val sensors = sensorHub.readings.value
                val pdr = pdrTracker.update(sensors)

                wsClient.send(
                    bleReadings = bleReadings,
                    sensors = sensors,
                    pdrDx = pdr?.dx ?: 0.0,
                    pdrDy = pdr?.dy ?: 0.0
                )

                updateNotification(
                    "Tracking — ${bleReadings.size} anchors visible"
                )
                delay(Config.WS_SEND_INTERVAL_MS)
            }
        }
    }

    private fun stopStreaming() {
        streamJob?.cancel()
        bleScanner.stop()
        sensorHub.stop()
        wsClient.disconnect()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ── Notification ─────────────────────────────────────────────────────────
    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Braket 1.5 Positioning",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Continuous BLE scanning for indoor positioning"
            setShowBadge(false)
        }
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
    }

    private fun buildNotification(status: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Braket 1.5")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setOngoing(true)
            .setSilent(true)
            .build()

    private fun updateNotification(status: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification(status))
    }

    companion object {
        const val ACTION_START = "com.braket.positioning.START"
        const val ACTION_STOP  = "com.braket.positioning.STOP"

        fun startIntent(context: Context) =
            Intent(context, BeaconForegroundService::class.java).apply { action = ACTION_START }

        fun stopIntent(context: Context) =
            Intent(context, BeaconForegroundService::class.java).apply { action = ACTION_STOP }
    }
}
