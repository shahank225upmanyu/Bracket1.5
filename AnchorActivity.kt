package com.braket.positioning.ui

import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.braket.positioning.R
import com.braket.positioning.anchor.AnchorBroadcaster
import com.braket.positioning.network.Config

class AnchorActivity : AppCompatActivity() {

    private var broadcaster: AnchorBroadcaster? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_anchor)

        val spinnerAnchor = findViewById<Spinner>(R.id.spinnerAnchorId)
        val btnToggle = findViewById<Button>(R.id.btnToggleBroadcast)
        val tvStatus = findViewById<TextView>(R.id.tvAnchorStatus)

        // Populate spinner with anchor IDs
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, Config.ANCHOR_IDS)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinnerAnchor.adapter = adapter

        btnToggle.setOnClickListener {
            if (broadcaster?.isRunning == true) {
                broadcaster?.stop()
                broadcaster = null
                btnToggle.text = "Start Broadcasting"
                tvStatus.text = "Stopped"
            } else {
                val anchorId = spinnerAnchor.selectedItem as String
                broadcaster = AnchorBroadcaster(this, anchorId)
                val ok = broadcaster!!.start()
                if (ok) {
                    btnToggle.text = "Stop Broadcasting"
                    tvStatus.text = "Broadcasting as $anchorId\nOther phones will see this beacon."
                } else {
                    tvStatus.text = "Failed to start BLE advertising.\nCheck Bluetooth is ON."
                }
            }
        }
    }

    override fun onDestroy() {
        broadcaster?.stop()
        super.onDestroy()
    }
}
