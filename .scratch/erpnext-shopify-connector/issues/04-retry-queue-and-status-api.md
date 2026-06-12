# Retry queue operations & status API

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 35, 36, 38.

## What to build

Implement the operational logic over the Retry Queue table from issue 01:

- Enqueue a pending sync operation (`direction`, `entity_type`, `payload`, optional `synced_entity_id` link).
- Process an item with exponential backoff on failure (increment `attempt_count`, compute `next_attempt_at`, record `last_error`).
- Transition an item to `dead_letter` after a configured maximum attempt count, retaining `last_error` for investigation rather than dropping it silently.

Expose FastAPI status endpoints to query the current state of Synced Entities and the retry/dead-letter queue (per user story 38), so operators can monitor sync health.

## Acceptance criteria

- [x] An enqueue function inserts a `pending` Retry Queue row with the given `direction`/`entity_type`/`payload` and optional Synced Entity link.
- [x] Processing a failed item increments `attempt_count`, records `last_error`, and computes `next_attempt_at` using exponential backoff.
- [x] After a configured max attempt count, an item transitions to `dead_letter` (not silently dropped) with `last_error` retained.
- [x] Pure logic tests cover the `pending → retry (with backoff)` and `retry → dead_letter` transitions over queue-row state, per the PRD's Testing Decisions.
- [x] FastAPI status endpoints return the current Synced Entity table and Retry Queue contents (filterable by status/entity_type), covered by `TestClient` tests.

## Blocked by

- 01-connector-scaffolding.md

## Comments

- Implemented: `connector/retry_queue.py` (`enqueue`, `record_failure` with exponential backoff `base_delay_seconds * 2**(attempt_count-1)` and `dead_letter` transition after `retry_max_attempts`, `record_success`), `connector/config.py` (new `retry_max_attempts`/`retry_base_delay_seconds` settings), `connector/api/status.py` (`GET /status/synced-entities` and `GET /status/retry-queue`, both filterable). Wired into `connector/main.py`. Tests in `tests/test_retry_queue.py` (6) and `tests/test_status_api.py` (2). `pytest -q` passes (58 passed total).
