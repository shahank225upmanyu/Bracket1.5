package com.braket.positioning.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.braket.positioning.R
import com.braket.positioning.network.BeaconForegroundService
import com.braket.positioning.target.BleScanner
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class TargetActivity : AppCompatActivity() {

    private lateinit var bleScanner: BleScanner

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_target)

        bleScanner = BleScanner(this)

        val tvAnchors = findViewById<TextView>(R.id.tvAnchorList)
        val tvStatus = findViewById<TextView>(R.id.tvTargetStatus)
        val btnStart = findViewById<Button>(R.id.btnStartTarget)
        val btnStop = findViewById<Button>(R.id.btnStopTarget)

        btnStart.setOnClickListener {
            // Start foreground service — keeps scanning alive in background
            ContextCompat.startForegroundService(
                this,
                BeaconForegroundService.startIntent(this)
            )
            tvStatus.text = "Streaming to server…"
        }

        btnStop.setOnClickListener {
            startService(BeaconForegroundService.stopIntent(this))
            tvStatus.text = "Stopped"
        }

        // UI-only BLE display (the service does the real work)
        bleScanner.start()
        lifecycleScope.launch {
            while (isActive) {
                val readings = bleScanner.getFreshReadings()
                val sb = StringBuilder()
                if (readings.isEmpty()) {
                    sb.append("No Braket anchors visible.\nMake sure anchor phones are running.")
                } else {
                    readings.sortedBy { it.anchorId }.forEach { r ->
                        val bar = rssiBar(r.rssi)
                        sb.append("${r.anchorId}  ${bar}  ${r.rssi} dBm  ~%.1fm\n".format(r.distanceMeters()))
                    }
                }
                tvAnchors.text = sb.toString()
                delay(200)
            }
        }
    }

    override fun onDestroy() {
        bleScanner.stop()
        super.onDestroy()
    }

    private fun rssiBar(rssi: Int): String {
        val level = ((rssi + 100).coerceIn(0, 60)) / 12   // 0–5 bars
        return "▮".repeat(level) + "▯".repeat(5 - level)
    }
}
