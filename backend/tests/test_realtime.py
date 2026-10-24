"""Real-time engine tests: run actual sessions against the model trained in the fixture."""
import asyncio
import time

import numpy as np
import pandas as pd
import pytest

from conftest import make_client


def wait_state(client, states=("finished", "stopped", "failed"), timeout=45):
    end = time.time() + timeout
    while time.time() < end:
        snap = client.get("/api/realtime/status").json()
        if snap["state"] in states:
            return snap
        time.sleep(0.25)
    raise AssertionError(f"session did not reach {states}; last={snap['state']}")


def scenario(client, seed=5, duration=6):
    classes = client.get("/api/realtime/scenarios").json()["classes"]
    flood = "DDoS" if "DDoS" in classes else next(c for c in classes if c != "BENIGN")
    return {"mode": "simulation", "scenario": {
        "name": "test", "seed": seed, "duration_seconds": duration, "baseline_rate": 30,
        "phases": [{"label": flood, "start": 2, "duration": 3, "rate": 60}]}}, flood


def test_scenarios_endpoint_lists_pool_and_presets(client):
    body = client.get("/api/realtime/scenarios").json()
    assert body["available"] and "BENIGN" in body["classes"] and body["presets"]
    assert "does not generate" in body["note"]
    assert client.get("/api/realtime/status").json()["state"] == "idle"


def test_simulation_session_detects_attack_phase_and_persists(client):
    req, flood = scenario(client)
    r = client.post("/api/realtime/sessions", json=req)
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "running"
    snap = wait_state(client)
    assert snap["state"] == "finished" and snap["session"]["stop_reason"] == "completed"

    assert snap["totals"]["flows"] > 100
    assert snap["latency_ms"]["p50"] is not None and snap["latency_ms"]["p50"] < 2000
    phase = snap["phases"][0]
    assert phase["label"] == flood and phase["flows"] > 50
    assert phase["first_detection_s"] is not None and phase["flagged"] > 0
    assert snap["truth"]["recall"] > 0.5  # the model is really scoring, not echoing labels
    assert snap["truth"]["flows_with_truth"] == snap["totals"]["flows"]

    scan = client.get(f"/api/scans/{snap['session']['scan_id']}").json()
    assert scan["source"] == "simulation" and scan["status"] == "completed"
    assert scan["records_stored"] == snap["totals"]["flows"]
    assert scan["summary"]["realtime"]["phases"] and scan["summary"]["label_comparison"]["n_samples"] == snap["totals"]["flows"]

    alerts = client.get("/api/alerts", params={"scan_id": scan["id"], "page_size": 5}).json()
    assert alerts["total"] > 0 and alerts["items"][0]["ground_truth_label"]
    assert client.get(f"/api/scans/{scan['id']}/report").status_code == 200


def test_same_seed_gives_same_flows(client):
    results = []
    for _ in range(2):
        req, _ = scenario(client, seed=21, duration=5)
        assert client.post("/api/realtime/sessions", json=req).status_code == 201
        snap = wait_state(client)
        results.append((snap["totals"]["flows"], snap["truth"]["tp"], snap["truth"]["fn"], snap["truth"]["tn"], snap["truth"]["fp"],
                        snap["phases"][0]["flows"]))
    assert results[0] == results[1]


def test_validation_conflict_and_stop(client):
    bad = {"mode": "simulation", "scenario": {"name": "x", "duration_seconds": 3, "baseline_rate": 10,
                                               "phases": [{"label": "Not A Class", "start": 0, "duration": 2, "rate": 5}]}}
    r = client.post("/api/realtime/sessions", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["problems"]
    too_fast = {"mode": "simulation", "scenario": {"name": "x", "duration_seconds": 10, "baseline_rate": 999999, "phases": []}}
    assert client.post("/api/realtime/sessions", json=too_fast).status_code == 422
    assert client.post("/api/realtime/sessions/stop").status_code == 409

    req, _ = scenario(client, duration=60)
    assert client.post("/api/realtime/sessions", json=req).status_code == 201
    assert client.post("/api/realtime/sessions", json=req).status_code == 409  # one session at a time
    time.sleep(1.5)
    assert client.post("/api/realtime/sessions/stop").status_code == 200
    snap = wait_state(client)
    assert snap["state"] == "stopped" and snap["session"]["stop_reason"] == "stopped by user"
    scan = client.get(f"/api/scans/{snap['session']['scan_id']}").json()
    assert scan["status"] == "completed" and scan["records_stored"] > 0


def test_external_feed_ingest(client, workspace):
    flows = pd.read_csv(workspace / "upload.csv", nrows=80)
    flows = flows.replace([np.inf, -np.inf], np.nan)  # JSON has no inf/NaN
    flows = flows.astype(object).where(flows.notna(), None).to_dict(orient="records")
    assert client.post("/api/realtime/ingest", json={"flows": flows[:2]}).status_code == 409  # no session yet
    assert client.post("/api/realtime/sessions", json={"mode": "live", "max_duration_seconds": 30}).status_code == 201
    assert client.post("/api/realtime/ingest", json={"flows": [{"Flow Duration": 1}]}).status_code == 422
    assert client.post("/api/realtime/ingest", json={"flows": flows}).json() == {"accepted": 80}
    time.sleep(1.5)
    client.post("/api/realtime/sessions/stop")
    snap = wait_state(client)
    assert snap["totals"]["flows"] == 80 and snap["truth"]["flows_with_truth"] == 80


def test_replay_of_uploaded_capture(client, workspace):
    small = workspace / "replay_small.csv"
    pd.read_csv(workspace / "upload.csv", nrows=300).to_csv(small, index=False)
    with open(small, "rb") as fh:
        up = client.post("/api/datasets/upload", files={"file": ("small.csv", fh, "text/csv")}).json()
    assert up["scan_id"]
    listed = client.get("/api/realtime/scenarios").json()["replayable_scans"]
    assert any(s["id"] == up["scan_id"] for s in listed)
    r = client.post("/api/realtime/sessions", json={"mode": "replay", "replay": {"scan_id": up["scan_id"], "rate": 200}})
    assert r.status_code == 201, r.text
    snap = wait_state(client)
    assert snap["state"] == "finished" and snap["totals"]["flows"] == 300
    assert client.post("/api/realtime/sessions", json={"mode": "replay", "replay": {"scan_id": "nope", "rate": 10}}).status_code == 404


def test_sse_events_are_pushed_to_subscribers(client):
    engine = client.app.state.container.realtime
    req, _ = scenario(client, duration=6)

    async def collect():
        q = engine.subscribe()
        try:
            from app.api.routes_realtime import start_session
            from app.schemas.api import SessionStart
            start_session(SessionStart(**req), client.app.state.container)
            events = []
            while len(events) < 3:
                events.append(await asyncio.wait_for(q.get(), 5))
            return events
        finally:
            engine.unsubscribe(q)

    events = asyncio.run(collect())
    assert events[0]["type"] in ("status", "tick") and all("totals" in e for e in events)
    engine.stop(wait=True)
    assert wait_state(client)["state"] == "stopped"


def test_health_unaffected_and_model_missing_blocks_sessions(workspace, tmp_path):
    with make_client(workspace, model_dir=tmp_path / "none") as c:
        assert c.get("/api/realtime/scenarios").json()["available"] is False
        assert c.post("/api/realtime/sessions", json={"mode": "live"}).status_code == 503


def test_dashboard_served_and_access_password(workspace, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>viona</html>")
    import os
    os.environ["VIONA_FRONTEND_DIR"], os.environ["VIONA_ACCESS_PASSWORD"] = str(dist), "s3cret"
    os.environ["NID_ALLOWED_ORIGINS"] = "https://viona.netlify.app"
    try:
        with make_client(workspace) as c:
            assert c.get("/live").status_code == 401 and "www-authenticate" in c.get("/live").headers  # page: browser prompt
            api401 = c.get("/api/scans")
            assert api401.status_code == 401 and "www-authenticate" not in api401.headers  # API: no popup, app shows its own login
            assert c.get("/api/health").status_code == 200  # probes stay open
            assert c.get("/live", auth=("any", "wrong")).status_code == 401
            ok = c.get("/live", auth=("any", "s3cret"))
            assert ok.status_code == 200 and "viona" in ok.text
            assert c.get("/api/nope", auth=("any", "s3cret")).status_code == 404
            # cross-origin browser flow (static site on Netlify): header key, preflight, stream/export query key
            origin = {"Origin": "https://viona.netlify.app"}
            pre = c.options("/api/scans", headers={**origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-viona-key"})
            assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "https://viona.netlify.app"
            denied = c.get("/api/scans", headers=origin)
            assert denied.status_code == 401 and denied.headers["access-control-allow-origin"] == "https://viona.netlify.app"
            assert c.get("/api/scans", headers={**origin, "X-Viona-Key": "s3cret"}).status_code == 200
            assert c.get("/api/scans?key=s3cret").status_code == 401  # query key is not accepted on ordinary routes
            assert c.get("/api/scans/x/export.csv?scope=all&key=s3cret").status_code != 401
    finally:
        for k in ("VIONA_FRONTEND_DIR", "VIONA_ACCESS_PASSWORD", "NID_ALLOWED_ORIGINS"):
            os.environ.pop(k, None)


def test_bundled_demo_model_loads_and_is_labelled_synthetic():
    """The model shipped in demo_model/ must load with this code, or hosted deploys start without a model."""
    from pathlib import Path
    from app.ml.model_store import ModelStore
    d = Path(__file__).resolve().parents[2] / "demo_model"
    store = ModelStore(d / "intrusion_model.joblib", d / "model_metadata.json", d / "evaluation.json")
    store.load()
    assert store.loaded, store.error
    assert store.is_synthetic and (d / "simulation_pool.joblib").exists()


def test_unreachable_postgres_falls_back_and_says_so(workspace):
    import os
    os.environ["DATABASE_URL"] = "postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=2"
    try:
        from conftest import Settings, create_app
        from fastapi.testclient import TestClient
        s = Settings(model_dir=workspace / "models", data_dir=workspace / "data", database_path=workspace / "data" / "fb.sqlite3")
        with TestClient(create_app(s)) as c:
            h = c.get("/api/health").json()
            assert h["database_ok"] and "Postgres unreachable" in h["database_error"]
    finally:
        os.environ.pop("DATABASE_URL")


def test_separate_db_fields_handle_awkward_passwords(monkeypatch):
    from app.core.config import _database_conninfo
    from psycopg.conninfo import conninfo_to_dict
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "aws-0-eu-west-1.pooler.supabase.com")
    monkeypatch.setenv("DB_USER", "postgres.abcdef")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/w#rd:1")
    d = conninfo_to_dict(_database_conninfo())
    assert d["host"] == "aws-0-eu-west-1.pooler.supabase.com" and d["password"] == "p@ss/w#rd:1"
    assert d["user"] == "postgres.abcdef" and d["sslmode"] == "require" and d["port"] == "5432"
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@h/db")  # a full URL still wins
    assert _database_conninfo() == "postgresql://x:y@h/db"
