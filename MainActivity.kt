package com.braket.positioning.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.braket.positioning.R

/**
 * Launch screen — user selects Anchor Mode or Target Mode.
 * Handles all runtime permission requests before proceeding.
 */
class MainActivity : AppCompatActivity() {

    private val permissionsToRequest: Array<String> by lazy {
        val list = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            list += Manifest.permission.BLUETOOTH_SCAN
            list += Manifest.permission.BLUETOOTH_ADVERTISE
            list += Manifest.permission.BLUETOOTH_CONNECT
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            list += Manifest.permission.NEARBY_WIFI_DEVICES
            list += Manifest.permission.POST_NOTIFICATIONS
        }
        list.toTypedArray()
    }

    private var pendingAction: (() -> Unit)? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val allGranted = results.values.all { it }
        if (allGranted) {
            pendingAction?.invoke()
        } else {
            Toast.makeText(
                this,
                "All permissions required for positioning. Please grant them in Settings.",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<Button>(R.id.btnAnchorMode).setOnClickListener {
            withPermissions { startActivity(Intent(this, AnchorActivity::class.java)) }
        }

        findViewById<Button>(R.id.btnTargetMode).setOnClickListener {
            withPermissions { startActivity(Intent(this, TargetActivity::class.java)) }
        }

        // Show server config hint
        val serverHint = "Server: ${com.braket.positioning.network.Config.WS_URL}"
        findViewById<TextView>(R.id.tvServerHint).text = serverHint
    }

    private fun withPermissions(action: () -> Unit) {
        val missing = permissionsToRequest.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) {
            action()
        } else {
            pendingAction = action
            permissionLauncher.launch(missing.toTypedArray())
        }
    }
}
