import base64
import hashlib
import hmac

from connector.shopify.webhooks import verify_webhook_hmac

SECRET = "test-webhook-secret"
BODY = b'{"id": 12345, "title": "Test Product"}'


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_valid_signature_passes():
    assert verify_webhook_hmac(BODY, _sign(BODY, SECRET), SECRET) is True


def test_invalid_signature_fails():
    wrong_signature = _sign(BODY, "a-different-secret")
    assert verify_webhook_hmac(BODY, wrong_signature, SECRET) is False


def test_tampered_body_fails():
    signature = _sign(BODY, SECRET)
    assert verify_webhook_hmac(BODY + b"tampered", signature, SECRET) is False


def test_missing_signature_fails():
    assert verify_webhook_hmac(BODY, None, SECRET) is False
    assert verify_webhook_hmac(BODY, "", SECRET) is False
