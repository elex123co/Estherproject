"""End-to-end API tests against a model that was really trained in the fixture."""
import io
import time

import pytest

from conftest import make_client


def wait_for(client, scan_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        scan = client.get(f"/api/scans/{scan_id}").json()
        if scan["status"] in ("completed", "failed"):
            return scan
        time.sleep(0.2)
    raise AssertionError("analysis did not finish")


def upload(client, path):
    with open(path, "rb") as fh:
        return client.post("/api/datasets/upload", files={"file": ("flows.csv", fh, "text/csv")})


def test_health_reports_checked_state(client):
    body = client.get("/api/health").json()
    assert body["model_loaded"] and body["database_ok"] and body["ready"] and body["status"] == "ok"
    assert body["model_is_synthetic"] is True


def test_health_degraded_when_model_missing(workspace, tmp_path):
    with make_client(workspace, model_dir=tmp_path / "nomodel") as c:
        body = c.get("/api/health").json()
        assert body["status"] == "degraded" and not body["model_loaded"] and body["model_error"]
        assert c.get("/api/model").status_code == 503
        assert c.post("/api/datasets/upload", files={"file": ("a.csv", b"x\n1\n", "text/csv")}).status_code == 503


def test_model_metadata_and_evaluation(client):
    meta = client.get("/api/model").json()
    assert meta["model_version"] and meta["features"] and meta["candidates"]
    assert set(meta["candidates"]) == {"random_forest", "decision_tree", "logistic_regression"}
    ev = client.get("/api/model/evaluation").json()
    sel = ev["selected"]
    assert sel["basis"] == "held-out test split"
    assert len(sel["confusion_matrix"]) == len(sel["labels"])
    assert "false_positive_rate" in sel["binary_detection"]


def test_empty_state_before_any_analysis(client):
    ov = client.get("/api/stats/overview").json()
    assert ov["total_records"] == 0 and ov["suspicious_records"] == 0
    tr = client.get("/api/stats/traffic").json()
    assert tr["trend"] == [] and tr["classification"] == {"normal": 0, "suspicious": 0}


def test_full_upload_analyze_review_export_flow(client, workspace):
    r = upload(client, workspace / "upload.csv")
    assert r.status_code == 200, r.text
    up = r.json()
    v = up["validation"]
    assert v["compatible"] and up["scan_id"]
    assert v["rows"] == 1212  # 1200 + duplicates appended by the generator
    assert v["duplicate_rows"] >= 1 and v["label_column_present"]
    assert v["missing_values"] + v["invalid_values"] > 0  # Infinity / NaN were injected

    scan_id = up["scan_id"]
    assert client.post(f"/api/scans/{scan_id}/analyze").status_code == 202
    scan = wait_for(client, scan_id)
    assert scan["status"] == "completed", scan.get("error")
    assert scan["rows_processed"] == 1212 and scan["records_stored"] == 1212
    # re-running the same scan is refused
    assert client.post(f"/api/scans/{scan_id}/analyze").status_code == 409

    # ground truth is kept separate from predictions
    comparison = scan["summary"]["label_comparison"]
    assert comparison["basis"] == "labels supplied in the uploaded file"

    ov = client.get("/api/stats/overview", params={"scan_id": scan_id}).json()
    assert ov["total_records"] == 1212
    assert ov["normal_records"] + ov["suspicious_records"] == 1212
    assert ov["suspicious_records"] > 0 and "not unique attacks" in ov["note"]

    tr = client.get("/api/stats/traffic", params={"scan_id": scan_id}).json()
    assert tr["time_basis"] == "flow_timestamp" and tr["trend"]
    assert sum(b["normal"] + b["suspicious"] for b in tr["trend"]) == 1212

    alerts = client.get("/api/alerts", params={"scan_id": scan_id, "page_size": 10}).json()
    assert alerts["total"] >= ov["suspicious_records"]
    first = alerts["items"][0]
    assert first["risk_rule_id"] and first["risk_reason"] and "features" not in first

    # filters
    crit = client.get("/api/alerts", params={"scan_id": scan_id, "risk_level": "High"}).json()
    assert all(i["risk_level"] == "High" for i in crit["items"])
    bad = client.get("/api/alerts", params={"risk_level": "Banana"})
    assert bad.status_code == 422
    assert client.get("/api/alerts", params={"date_from": "not-a-date"}).status_code == 422

    # detail, then review
    detail = client.get(f"/api/alerts/{first['id']}").json()
    assert detail["confidence_note"] and detail["review_status"] == "new"
    patched = client.patch(f"/api/alerts/{first['id']}", json={"review_status": "investigating", "review_note": "checking firewall logs"}).json()
    assert patched["review_status"] == "investigating" and patched["review_note"] == "checking firewall logs"
    assert client.patch(f"/api/alerts/{first['id']}", json={"review_status": "bogus"}).status_code == 422
    assert client.patch(f"/api/alerts/{first['id']}", json={}).status_code == 422
    assert client.patch("/api/alerts/doesnotexist", json={"review_status": "reviewed"}).status_code == 404
    inv = client.get("/api/alerts", params={"scan_id": scan_id, "review_status": "investigating"}).json()
    assert inv["total"] == 1

    # export + report
    csv_resp = client.get(f"/api/scans/{scan_id}/export.csv", params={"scope": "alerts"})
    assert csv_resp.status_code == 200 and "potential intrusions" in csv_resp.text.splitlines()[0]
    header = csv_resp.text.splitlines()[1]
    assert "risk_level" in header and "src_ip" not in header  # no network context unless requested
    ctx = client.get(f"/api/scans/{scan_id}/export.csv", params={"include_network_context": "true"})
    assert "src_ip" in ctx.text.splitlines()[1]
    rep = client.get(f"/api/scans/{scan_id}/report").json()
    assert rep["model"]["version"] == scan["model_version"] and rep["disclaimer"] and rep["top_alerts"]

    # delete cascades
    assert client.delete(f"/api/scans/{scan_id}").status_code == 204
    assert client.get(f"/api/scans/{scan_id}").status_code == 404
    assert client.get("/api/stats/overview").json()["total_records"] == 0


def test_incompatible_csv_gets_clear_error(client):
    csv_bytes = b"Alpha,Beta,Label\n1,2,BENIGN\n3,4,DDoS\n"
    r = client.post("/api/datasets/upload", files={"file": ("bad.csv", io.BytesIO(csv_bytes), "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["scan_id"] is None and not body["validation"]["compatible"]
    assert "missing" in body["validation"]["errors"][0]


def test_rejects_wrong_extension_empty_and_oversized(client):
    assert client.post("/api/datasets/upload", files={"file": ("x.pcap", b"abc", "application/octet-stream")}).status_code == 415
    assert client.post("/api/datasets/upload", files={"file": ("x.csv", b"", "text/csv")}).status_code == 400
    big = b"a,b\n" + b"1,2\n" * (6 * 1024 * 1024 // 4)
    assert client.post("/api/datasets/upload", files={"file": ("big.csv", big, "text/csv")}).status_code == 413
    assert client.post("/api/datasets/upload", files={"file": ("x.csv", b"\x00\x01\x02garbage", "text/csv")}).status_code in (200, 422)


def test_single_record_prediction_and_schema_errors(client, workspace):
    import pandas as pd
    row = pd.read_csv(workspace / "upload.csv", nrows=1).iloc[0].to_dict()
    row = {k: (None if pd.isna(v) else v) for k, v in row.items()}
    r = client.post("/api/predict", json={"record": row})
    assert r.status_code == 200, r.text
    out = r.json()
    for key in ("record_id", "predicted_class", "is_suspicious", "confidence", "risk_level", "risk_reason", "processed_at"):
        assert key in out
    assert 0.0 <= out["confidence"] <= 1.0
    # missing fields -> 422 listing the problem, not a crash
    bad = client.post("/api/predict", json={"record": {"Flow Duration": 5}})
    assert bad.status_code == 422 and "missing" in str(bad.json()).lower()
    assert client.post("/api/predict", json={}).status_code == 422


def test_unknown_scan_and_dataset_schema(client):
    assert client.get("/api/scans/nope").status_code == 404
    assert client.post("/api/scans/nope/analyze").status_code == 404
    schema = client.get("/api/datasets/schema").json()
    assert schema["required_features"] and "pcap" in " ".join(schema["notes"]).lower()
    assert client.get("/api/risk/rules").json()["category_rules"]
