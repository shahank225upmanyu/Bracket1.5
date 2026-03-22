package com.braket.positioning.security

import android.util.Base64
import com.braket.positioning.network.Config
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Signs every outgoing JSON payload with HMAC-SHA256.
 * The server verifies the signature before processing any packet.
 * This prevents spoofed packets from fake anchors injecting false positions.
 */
object PacketSigner {

    private val mac: Mac by lazy {
        Mac.getInstance("HmacSHA256").apply {
            init(SecretKeySpec(Config.HMAC_SECRET.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        }
    }

    /**
     * Returns Base64-encoded HMAC-SHA256 of [payload].
     * Thread-safe: clones the Mac instance per call.
     */
    fun sign(payload: String): String {
        val localMac = mac.clone() as Mac
        val raw = localMac.doFinal(payload.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(raw, Base64.NO_WRAP)
    }

    /** Returns true if [signature] matches HMAC of [payload]. */
    fun verify(payload: String, signature: String): Boolean {
        return try {
            sign(payload) == signature
        } catch (e: Exception) {
            false
        }
    }
}
