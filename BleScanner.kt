package com.braket.positioning.target

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanRecord
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.ParcelUuid
import android.util.Log
import com.braket.positioning.network.Config
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/**
 * Runs on the TARGET phone.
 *
 * Performs continuous BLE scanning filtered to the Braket 1.5 service UUID.
 * Scan mode LOW_LATENCY = ~100 ms scan cycle = ~10 Hz updates.
 * No Android scan throttling applies to foreground BLE scans.
 *
 * Emits [anchorReadings] — a map of anchorId → [BleReading].
 * Readings older than STALE_MS are automatically dropped.
 */
class BleScanner(context: Context) {

    private val TAG = "BleScanner"
    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val adapter: BluetoothAdapter? = bluetoothManager.adapter
    private var scanner: BluetoothLeScanner? = null
    private var isScanning = false

    private val STALE_MS = 2_000L  // drop readings older than 2 s

    // Map: anchorId → latest reading
    private val _anchorReadings = MutableStateFlow<Map<String, BleReading>>(emptyMap())
    val anchorReadings: StateFlow<Map<String, BleReading>> = _anchorReadings

    private val scanFilter = ScanFilter.Builder()
        .setServiceUuid(ParcelUuid(UUID.fromString(Config.BLE_SERVICE_UUID)))
        .build()

    private val scanSettings = ScanSettings.Builder()
        .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)        // Maximum duty cycle, ~10 Hz
        .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
        .setMatchMode(ScanSettings.MATCH_MODE_AGGRESSIVE)
        .setNumOfMatches(ScanSettings.MATCH_NUM_MAX_ADVERTISEMENT)
        .setReportDelay(0L)    // deliver results immediately (not batched)
        .build()

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            processScanResult(result)
        }
        override fun onBatchScanResults(results: List<ScanResult>) {
            results.forEach { processScanResult(it) }
        }
        override fun onScanFailed(errorCode: Int) {
            val reason = when (errorCode) {
                SCAN_FAILED_ALREADY_STARTED -> "already started"
                SCAN_FAILED_APPLICATION_REGISTRATION_FAILED -> "app registration failed"
                SCAN_FAILED_FEATURE_UNSUPPORTED -> "BLE scan unsupported"
                SCAN_FAILED_INTERNAL_ERROR -> "internal error"
                else -> "error $errorCode"
            }
            Log.e(TAG, "BLE scan failed: $reason")
            isScanning = false
        }
    }

    private fun processScanResult(result: ScanResult) {
        val record: ScanRecord = result.scanRecord ?: return
        val mfData = record.getManufacturerSpecificData(Config.BLE_MANUFACTURER_ID) ?: return
        if (mfData.size < 2) return

        val anchorIndex = mfData[0].toInt()
        val anchorId = Config.ANCHOR_IDS.getOrNull(anchorIndex) ?: return

        val txPower = result.txPower.takeIf { it != ScanResult.TX_POWER_NOT_PRESENT }
            ?: record.txPowerLevel.takeIf { it != Int.MIN_VALUE }
            ?: -59  // fallback default if not advertised

        val reading = BleReading(
            anchorId = anchorId,
            deviceAddress = result.device.address,
            rssi = result.rssi,
            txPower = txPower,
            timestampMs = System.currentTimeMillis()
        )

        // Merge into current map, removing stale entries
        val now = System.currentTimeMillis()
        val updated = (_anchorReadings.value + (anchorId to reading))
            .filter { now - it.value.timestampMs < STALE_MS }
        _anchorReadings.value = updated
    }

    fun start(): Boolean {
        if (adapter == null || !adapter.isEnabled) {
            Log.e(TAG, "Bluetooth adapter not available")
            return false
        }
        if (isScanning) return true
        scanner = adapter.bluetoothLeScanner
        if (scanner == null) {
            Log.e(TAG, "BLE scanner not available")
            return false
        }
        try {
            scanner!!.startScan(listOf(scanFilter), scanSettings, scanCallback)
            isScanning = true
            Log.i(TAG, "BLE scan started")
            return true
        } catch (e: SecurityException) {
            Log.e(TAG, "Missing BLUETOOTH_SCAN permission: ${e.message}")
            return false
        }
    }

    fun stop() {
        if (!isScanning) return
        try {
            scanner?.stopScan(scanCallback)
        } catch (e: SecurityException) {
            Log.e(TAG, "Cannot stop scan: ${e.message}")
        }
        isScanning = false
        Log.i(TAG, "BLE scan stopped")
    }

    /** Returns the freshest readings for all known anchors. */
    fun getFreshReadings(): List<BleReading> {
        val now = System.currentTimeMillis()
        return _anchorReadings.value.values.filter { now - it.timestampMs < STALE_MS }
    }

    val isRunning get() = isScanning
}

data class BleReading(
    val anchorId: String,
    val deviceAddress: String,
    val rssi: Int,          // dBm — typically -40 (close) to -95 (far)
    val txPower: Int,       // dBm transmitted power, from ad packet
    val timestampMs: Long
) {
    /** Path-loss corrected distance estimate in metres. */
    fun distanceMeters(n: Double = 2.8): Double {
        val diff = (txPower - rssi).toDouble()
        return Math.pow(10.0, diff / (10.0 * n))
    }
}
