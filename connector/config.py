from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Shopify custom app credentials (per ADR-0001: GraphQL Admin API only)
    shopify_shop_domain: str
    shopify_api_version: str = "2026-04"
    shopify_api_key: str
    shopify_api_secret: str
    shopify_access_token: str
    shopify_webhook_secret: str

    # ERPNext / Frappe REST API credentials
    erpnext_url: str
    erpnext_api_key: str
    erpnext_api_secret: str

    # Single Shopify Location <-> ERPNext Warehouse pairing (per PRD)
    shopify_location_gid: str
    erpnext_warehouse: str

    # Public base URL the Connector's webhook-receiver endpoints are reachable at
    # (e.g. an ngrok/Cloudflare Tunnel URL in local development, per PRD).
    connector_base_url: str

    # Synced Entity / Retry Queue store
    database_url: str = "sqlite:///./connector.db"

    # Retry queue: max attempts before an item moves to dead_letter, and the
    # base delay (seconds) for exponential backoff between attempts.
    retry_max_attempts: int = 5
    retry_base_delay_seconds: int = 60

    @property
    def shopify_graphql_url(self) -> str:
        return f"https://{self.shopify_shop_domain}/admin/api/{self.shopify_api_version}/graphql.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
