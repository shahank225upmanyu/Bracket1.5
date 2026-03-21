package com.example.wifiscanner

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.wifi.ScanResult
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var wifiManager: WifiManager
    private lateinit var tvResults: TextView
    private lateinit var btnScan: Button

    // Modern way to handle permissions
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val granted = permissions.entries.all { it.value }
        if (granted) {
            startWifiScan()
        } else {
            Toast.makeText(this, "Permissions Denied! Can't scan.", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvResults = findViewById(R.id.tvResults)
        btnScan = findViewById(R.id.btnScan)
        wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

        btnScan.setOnClickListener {
            checkPermissionsAndScan()
        }
    }

    private fun checkPermissionsAndScan() {
        val permissionsNeeded = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION)
        
        // Android 13 (API 33) and above needs NEARBY_WIFI_DEVICES
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissionsNeeded.add(Manifest.permission.NEARBY_WIFI_DEVICES)
        }

        if (permissionsNeeded.all { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }) {
            startWifiScan()
        } else {
            requestPermissionLauncher.launch(permissionsNeeded.toTypedArray())
        }
    }

    private fun startWifiScan() {
        val wifiScanReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val success = intent.getBooleanExtra(WifiManager.EXTRA_RESULTS_UPDATED, false)
                if (success) {
                    displayScanResults()
                } else {
                    Log.e("WiFiScan", "Scan Throttled or Failed")
                    tvResults.text = "Scan failed or throttled. Wait 30s and try again."
                }
                // Unregister to avoid memory leaks
                unregisterReceiver(this)
            }
        }

        registerReceiver(wifiScanReceiver, IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION))

        val success = wifiManager.startScan()
        if (!success) {
            tvResults.text = "Scan start failed. Check if GPS is ON."
        } else {
            Toast.makeText(this, "Scanning...", Toast.LENGTH_SHORT).show()
        }
    }

    private fun displayScanResults() {
        val results: List<ScanResult> = wifiManager.scanResults
        val sb = StringBuilder()
        sb.append("Found ${results.size} Networks:\n\n")

        for (result in results) {
            val ssid = if (result.SSID.isEmpty()) "[Hidden Network]" else result.SSID
            sb.append("📡 SSID: $ssid\n")
            sb.append("💪 Strength: ${result.level} dBm\n")
            sb.append("📍 BSSID: ${result.BSSID}\n")
            sb.append("--------------------------\n")
            
            Log.d("WiFiScan", "Found: $ssid")
        }

        tvResults.text = sb.toString()
    }
}