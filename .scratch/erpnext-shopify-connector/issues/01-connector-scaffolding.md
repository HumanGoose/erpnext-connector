# Connector scaffolding: config, FastAPI app, Synced Entity & Retry Queue schema

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 39.

## What to build

Set up the Connector as a standalone Python/FastAPI service (per ADR-0002). Establish the project structure, dependency management, and a configuration layer that loads Shopify app credentials (API key/secret, offline access token), the webhook HMAC secret, ERPNext connection details (URL, API key/secret for `frappeclient`), and the single Shopify Location ↔ ERPNext Warehouse pairing — all from environment/config, not hardcoded.

Set up SQLModel + SQLite as the persistence layer with the two stores from the PRD's conceptual schema:

- **Synced Entity**: `entity_type`, `shopify_gid`, `erpnext_doctype`, `erpnext_name`, `shopify_fingerprint`, `erpnext_fingerprint`, `last_synced_at`.
- **Retry Queue**: `synced_entity_id` (nullable FK), `direction`, `entity_type`, `payload`, `attempt_count`, `next_attempt_at`, `status`, `last_error`.

Stand up a minimal FastAPI app with a health-check endpoint to confirm the service runs and connects to its database.

## Acceptance criteria

- [ ] Connector runs as a standalone FastAPI service (`uvicorn` entrypoint), separate from Shopify and ERPNext.
- [ ] Configuration (Shopify credentials, webhook secret, ERPNext connection, Location↔Warehouse pairing) is loaded from environment/config, with no secrets hardcoded; missing required config fails fast at startup.
- [ ] SQLModel models exist for the Synced Entity and Retry Queue tables matching the PRD's conceptual schema, backed by SQLite, with a working initialization path.
- [ ] A health-check endpoint confirms the app is up and the database is reachable.
- [ ] A test runner (e.g. pytest) is set up, with at least a smoke test exercising the health-check endpoint and DB initialization.

## Blocked by

None - can start immediately.

## Comments

- Implemented: `pyproject.toml` (FastAPI/SQLModel/pydantic-settings/httpx, pytest+httpx2 for dev), `connector/config.py` (fail-fast `Settings` via pydantic-settings), `connector/models.py` (`SyncedEntity`, `RetryQueueEntry` SQLModel tables with `EntityType`/`SyncDirection`/`RetryStatus` enums per PRD schema), `connector/db.py` (SQLite engine + `init_db`/`get_session`), `connector/main.py` (FastAPI app, lifespan-based `init_db`), `connector/api/health.py` (`GET /health`). `.env.example` documents required config. `tests/conftest.py` + `tests/test_health.py` cover the smoke test. Verified `uvicorn connector.main:app` runs and `/health` returns `{"status": "ok"}`, and that missing required env vars raise a fail-fast `ValidationError` at import time. `pytest -q` passes (1 passed).
