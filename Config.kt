package com.braket.positioning.network

object Config {
    // ── Change this to your laptop's LAN IP ──────────────────────────────────
    const val SERVER_IP = "192.168.1.100"
    const val SERVER_WS_PORT = 8765
    const val SERVER_HTTP_PORT = 8000

    val WS_URL get() = "ws://$SERVER_IP:$SERVER_WS_PORT/ws"
    val HTTP_URL get() = "http://$SERVER_IP:$SERVER_HTTP_PORT"

    // ── Security ──────────────────────────────────────────────────────────────
    // MUST match server/utils/auth.py SECRET_KEY
    const val HMAC_SECRET = "braket-1.5-secret-change-in-production"

    // ── BLE Beacon ────────────────────────────────────────────────────────────
    // 16-byte UUID for Braket 1.5 service — unique to this project
    const val BLE_SERVICE_UUID = "0000BCA1-0000-1000-8000-00805F9B34FB"
    const val BLE_MANUFACTURER_ID = 0x0B_CA  // "Braket" manufacturer code

    // ── Scanning ──────────────────────────────────────────────────────────────
    const val BLE_SCAN_INTERVAL_MS = 100L      // 10 Hz scan window
    const val BLE_SCAN_WINDOW_MS = 100L
    const val SENSOR_SAMPLE_RATE_US = 20_000   // 50 Hz IMU

    // ── Timing ────────────────────────────────────────────────────────────────
    const val WS_SEND_INTERVAL_MS = 100L       // 10 Hz stream to server
    const val WS_RECONNECT_DELAY_MS = 2_000L
    const val WS_PING_INTERVAL_MS = 5_000L

    // ── Anchor IDs ────────────────────────────────────────────────────────────
    val ANCHOR_IDS = listOf("BRAKET-A", "BRAKET-B", "BRAKET-C", "BRAKET-D")
}
