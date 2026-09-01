import hashlib
import hmac
from typing import Optional


def verify_meta_signature(body: bytes, signature: Optional[str], app_secret: str) -> bool:
    if not signature or not signature.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)
