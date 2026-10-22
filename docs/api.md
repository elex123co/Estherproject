# API reference
Interactive, always-current documentation is served by the backend at `/docs` (Swagger UI) and `/openapi.json`.
Errors use `{"detail": ...}` with 4xx for client problems (404 unknown id, 409 wrong scan state, 413 oversized upload,
415 non-CSV, 422 invalid input or schema mismatch, 429 queue full) and 503 when the model is not loaded.


## Real-time (`/api/realtime`)

| Method and path | Purpose |
|---|---|
| `GET /scenarios` | Preset scenarios, simulation classes and counts, limits, replayable uploads. |
| `GET /status` | Current session snapshot (`idle`, `running`, `finished`, `stopped`, `failed`). |
| `POST /sessions` | Start a session. Body `{"mode": "simulation", "scenario": {name, seed?, duration_seconds, baseline_rate, phases: [{label, start, duration, rate}]}}`, `{"mode": "replay", "replay": {scan_id, rate, loop}}` or `{"mode": "live", "max_duration_seconds"}`. 201 on success, 409 if a session is running, 422 with `problems` if invalid, 503 if no model. |
| `POST /sessions/stop` | Stop the running session. 409 if none. |
| `POST /ingest` | Body `{"flows": [{feature: value, ...}]}`, 1 to 500 flows, into a `live` session. 409 no live session, 422 schema mismatch, 429 queue full. JSON cannot carry inf or NaN: send null. |
| `GET /stream` | Server-Sent Events: `snapshot` on connect, then `tick` (every 500 ms) and `status` events. |

Snapshots contain `totals`, `rate`, `latency_ms`, `series` (per second), `phases` (with `first_detection_s` and `recall`), `truth` (only when labels are known) and `recent_alerts`.
