import os
import tempfile
from pathlib import Path

_tmp_dir = tempfile.mkdtemp(prefix="connector-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(_tmp_dir) / 'test.db'}")
os.environ.setdefault("SHOPIFY_SHOP_DOMAIN", "test-shop.myshopify.com")
os.environ.setdefault("SHOPIFY_API_KEY", "test-api-key")
os.environ.setdefault("SHOPIFY_API_SECRET", "test-api-secret")
os.environ.setdefault("SHOPIFY_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("SHOPIFY_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("ERPNEXT_URL", "https://erpnext.test")
os.environ.setdefault("ERPNEXT_API_KEY", "test-erpnext-key")
os.environ.setdefault("ERPNEXT_API_SECRET", "test-erpnext-secret")
os.environ.setdefault("SHOPIFY_LOCATION_GID", "gid://shopify/Location/1")
os.environ.setdefault("ERPNEXT_WAREHOUSE", "Stores - TC")
os.environ.setdefault("CONNECTOR_BASE_URL", "https://connector.test")
