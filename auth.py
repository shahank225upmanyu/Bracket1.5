"""
utils/auth.py — Server-side HMAC-SHA256 packet authentication.

Every packet from the Target phone carries a 'sig' field.
This module verifies it matches the expected HMAC of the payload body.
Packets that fail verification are silently dropped and logged.
"""

import hashlib
import hmac
import json
from utils.config import SECRET_KEY


def _sign(payload_str: str) -> str:
    """Returns Base64-encoded HMAC-SHA256 of payload_str."""
    import base64
    raw = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(raw).decode("ascii")


def verify_packet(raw_json: str) -> tuple[bool, dict | None]:
    """
    Parse [raw_json] and verify its HMAC signature.

    Returns:
        (True, packet_dict) if valid
        (False, None) if invalid or malformed
    """
    try:
        packet = json.loads(raw_json)
    except json.JSONDecodeError:
        return False, None

    received_sig = packet.pop("sig", None)
    if received_sig is None:
        return False, None  # No signature at all — reject

    # Re-serialise without the sig field (same as how Android built the payload)
    payload_str = json.dumps(packet, separators=(",", ":"), sort_keys=False)
    expected_sig = _sign(payload_str)

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(received_sig, expected_sig):
        return False, None

    return True, packet
