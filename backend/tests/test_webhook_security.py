import hashlib
import hmac

from app.webhook_security import verify_meta_signature


def test_meta_signature_accepts_valid_sha256_digest():
    body = b'{"entry":[]}'
    secret = "app-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_meta_signature(body, signature, secret)


def test_meta_signature_rejects_missing_or_tampered_digest():
    assert not verify_meta_signature(b"payload", None, "secret")
    assert not verify_meta_signature(b"payload", "sha256=bad", "secret")
