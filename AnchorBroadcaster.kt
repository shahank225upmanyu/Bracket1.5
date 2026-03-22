package com.braket.positioning.anchor

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.Context
import android.os.ParcelUuid
import android.util.Log
import com.braket.positioning.network.Config
import java.nio.ByteBuffer
import java.util.UUID

/**
 * Runs on an ANCHOR phone.
 *
 * Broadcasts a BLE advertisement at maximum power containing:
 *   - Braket service UUID (identifies this as a Braket 1.5 beacon)
 *   - Anchor ID byte (A=0, B=1, C=2, D=3)
 *   - Tx power byte (for path loss calibration on the receiver side)
 *
 * The Target phone reads RSSI + Tx power to compute path-loss distance.
 * Advertising at ~10 Hz allows the target to scan at full 10 Hz rate.
 */
class AnchorBroadcaster(
    context: Context,
    private val anchorId: String     // e.g. "BRAKET-A"
) {
    private val TAG = "AnchorBroadcaster"
    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val adapter: BluetoothAdapter? = bluetoothManager.adapter
    private var advertiser: BluetoothLeAdvertiser? = null
    private var isAdvertising = false

    private val serviceUuid = ParcelUuid(UUID.fromString(Config.BLE_SERVICE_UUID))

    // Anchor index 0–3 packed into manufacturer data
    private val anchorIndex: Byte = when (anchorId) {
        "BRAKET-A" -> 0
        "BRAKET-B" -> 1
        "BRAKET-C" -> 2
        "BRAKET-D" -> 3
        else -> 0
    }

    private val advertiseSettings = AdvertiseSettings.Builder()
        .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)   // ~100 ms interval
        .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
        .setConnectable(false)          // Beacon only — no GATT connection needed
        .setTimeout(0)                  // Advertise indefinitely
        .build()

    private val advertiseData = AdvertiseData.Builder()
        .addServiceUuid(serviceUuid)
        .addManufacturerData(
            Config.BLE_MANUFACTURER_ID,
            ByteBuffer.allocate(2).put(anchorIndex).put(0x01).array()   // [anchorIdx, version]
        )
        .setIncludeTxPowerLevel(true)   // Receiver uses this for path loss correction
        .setIncludeDeviceName(false)    // Save packet space
        .build()

    private val callback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
            isAdvertising = true
            Log.i(TAG, "[$anchorId] BLE advertising started. Mode=${settingsInEffect.mode}")
        }
        override fun onStartFailure(errorCode: Int) {
            isAdvertising = false
            val reason = when (errorCode) {
                ADVERTISE_FAILED_ALREADY_STARTED -> "already started"
                ADVERTISE_FAILED_DATA_TOO_LARGE -> "data too large"
                ADVERTISE_FAILED_FEATURE_UNSUPPORTED -> "BLE advertising unsupported on this device"
                ADVERTISE_FAILED_INTERNAL_ERROR -> "internal error"
                ADVERTISE_FAILED_TOO_MANY_ADVERTISERS -> "too many advertisers"
                else -> "unknown error $errorCode"
            }
            Log.e(TAG, "[$anchorId] Advertising failed: $reason")
        }
    }

    fun start(): Boolean {
        if (adapter == null || !adapter.isEnabled) {
            Log.e(TAG, "Bluetooth not available or disabled")
            return false
        }
        if (isAdvertising) return true
        advertiser = adapter.bluetoothLeAdvertiser
        if (advertiser == null) {
            Log.e(TAG, "BLE advertising not supported on this hardware")
            return false
        }
        try {
            advertiser!!.startAdvertising(advertiseSettings, advertiseData, callback)
            return true
        } catch (e: SecurityException) {
            Log.e(TAG, "Missing BLUETOOTH_ADVERTISE permission: ${e.message}")
            return false
        }
    }

    fun stop() {
        if (!isAdvertising) return
        try {
            advertiser?.stopAdvertising(callback)
        } catch (e: SecurityException) {
            Log.e(TAG, "Cannot stop advertising: ${e.message}")
        }
        isAdvertising = false
        Log.i(TAG, "[$anchorId] BLE advertising stopped")
    }

    val isRunning get() = isAdvertising
}
