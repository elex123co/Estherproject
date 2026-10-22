"""Real-time detection engine.

A background thread runs a continuous micro-batch loop:

    source (simulated scenario | replayed capture | external feed)
      -> every 100 ms: collect the flows that arrived
      -> saved preprocessing + model -> risk rules
      -> persisted to SQLite (so alerts, review, reports and exports work on live data)
      -> live state pushed to the browser every 500 ms (Server-Sent Events)

Measured live, not estimated: throughput, detection latency (flow arrival to prediction complete,
including the micro-batch wait), and - when ground truth is known - precision, recall, false alarms and
time-to-first-detection per attack phase. Ground truth is used only for scoring, never by the model.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..core.config import Settings
from ..database.repository import Repository, utcnow
from ..ml.evaluation import evaluate_from_confusion
from ..ml.schema import BENIGN_LABEL
from .prediction import MissingFeaturesError, Predictor
from .simulation import LiveSource, Source

log = logging.getLogger("nid.realtime")

TICK_SECONDS = 0.1
PUBLISH_SECONDS = 0.5
SERIES_SECONDS = 120
RECENT_ALERTS = 100
MAX_ALERTS_PER_TICK = 40
LATENCY_RESERVOIR = 5000


class SessionConflict(Exception):
    pass


class SessionError(Exception):
    pass


def _pct(values, q: float) -> float | None:
    return float(np.percentile(values, q)) if len(values) else None


@dataclass
class _Session:
    id: str
    scan_id: str
    mode: str
    name: str
    source: Source
    scenario: dict | None
    started_at: str
    mono_start: float
    wall_start: float
    max_seconds: float | None
    state: str = "running"
    stop_reason: str | None = None
    error: str | None = None
    processed: int = 0
    suspicious: int = 0
    needs_review: int = 0
    risk: Counter = field(default_factory=Counter)
    pred_counts: Counter = field(default_factory=Counter)
    series: dict = field(default_factory=dict)          # second -> [normal, suspicious]
    latencies: deque = field(default_factory=lambda: deque(maxlen=LATENCY_RESERVOIR))
    batch_ms: deque = field(default_factory=lambda: deque(maxlen=600))
    throughput: deque = field(default_factory=deque)    # (t_done, n) for the last few seconds
    truth: dict = field(default_factory=lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    confusion: Counter = field(default_factory=Counter)
    phase_stats: dict = field(default_factory=dict)
    recent_alerts: deque = field(default_factory=lambda: deque(maxlen=RECENT_ALERTS))
    pending_alerts: list = field(default_factory=list)
    suppressed_alerts: int = 0
    feature_budget: int = 0
    elapsed: float = 0.0
    stop: threading.Event = field(default_factory=threading.Event)


class RealtimeEngine:
    def __init__(self, settings: Settings, repo: Repository, predictor: Predictor, pool):
        self.settings = settings
        self.repo = repo
        self.predictor = predictor
        self.pool = pool
        self._session: _Session | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._cache: dict = self._idle_snapshot()

    # ------------------------------------------------------------------ public
    @property
    def active(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def snapshot(self) -> dict:
        return self._cache

    def start(self, source: Source, *, mode: str, name: str, scenario: dict | None = None,
              max_seconds: float | None = None) -> dict:
        with self._start_lock:
            if self.active:
                raise SessionConflict("A real-time session is already running. Stop it first.")
            prefix = {"simulation": "Simulation", "replay": "Replay", "live": "Live feed"}.get(mode, mode)
            scan_id = self.repo.create_scan(
                source=mode, filename=f"{prefix}: {name}", file_path=None, size_bytes=None, status="running",
                rows_total=None, validation=None, model_version=self.predictor.store.version)
            self.repo.update_scan(scan_id, started_at=utcnow())
            session = _Session(
                id=uuid.uuid4().hex, scan_id=scan_id, mode=mode, name=name, source=source, scenario=scenario,
                started_at=utcnow(), mono_start=time.monotonic(), wall_start=time.time(), max_seconds=max_seconds,
                feature_budget=self.settings.max_feature_rows_per_scan)
            source.mono_start = session.mono_start
            for p in source.planned_phases():
                session.phase_stats[p.idx] = {"flows": 0, "flagged": 0, "correct_category": 0, "first_detection_s": None}
            self._session = session
            self._cache = self._build_snapshot(session)
            self._thread = threading.Thread(target=self._run, args=(session,), daemon=True, name="realtime-engine")
            self._thread.start()
        self._broadcast({"type": "status", **self._cache, "new_alerts": []})
        return self._cache

    def stop(self, wait: bool = False, timeout: float = 10.0) -> dict:
        session = self._session
        if session is None or not self.active:
            raise SessionError("No real-time session is running.")
        session.stop.set()
        if wait and self._thread:
            self._thread.join(timeout)
        return self._cache

    def ingest(self, flows: list[dict[str, Any]]) -> int:
        session = self._session
        if session is None or not self.active or not isinstance(session.source, LiveSource):
            raise SessionError("No external-feed session is running. Start one with mode 'live' first.")
        missing = [f for f in self.predictor.store.features if f not in {str(k).strip() for k in flows[0]}] if flows else []
        if missing:
            raise MissingFeaturesError(missing)
        for flow in flows[1:]:
            keys = {str(k).strip() for k in flow}
            if any(f not in keys for f in self.predictor.store.features):
                raise MissingFeaturesError([f for f in self.predictor.store.features if f not in keys])
        return session.source.push(flows)

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        with self._sub_lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._sub_lock:
            self._subs = [(l, x) for (l, x) in self._subs if x is not q]

    def shutdown(self) -> None:
        if self.active:
            self._session.stop.set()  # type: ignore[union-attr]
            self._thread.join(5)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ thread
    def _run(self, s: _Session) -> None:
        last = 0.0
        next_publish = 0.0
        try:
            while True:
                loop_start = time.monotonic()
                now = loop_start - s.mono_start
                if s.stop.is_set():
                    s.stop_reason = s.stop_reason or "stopped by user"
                    break
                batch = s.source.next_batch(last, now)
                last = now
                if batch is not None and len(batch.frame):
                    self._process(s, batch)
                s.elapsed = now
                if s.processed >= self.settings.max_realtime_records:
                    s.stop_reason = f"record limit of {self.settings.max_realtime_records:,} reached"
                    break
                if s.source.finished(now) or (s.max_seconds and now >= s.max_seconds):
                    s.stop_reason = "completed"
                    break
                if now >= next_publish:
                    self._publish(s, "tick")
                    next_publish = now + PUBLISH_SECONDS
                s.stop.wait(max(0.0, TICK_SECONDS - (time.monotonic() - loop_start)))
        except Exception as exc:  # noqa: BLE001 - reported on the session and the scan
            log.exception("Real-time session failed")
            s.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._finalize(s)

    def _process(self, s: _Session, batch) -> None:
        t_begin = time.monotonic()
        frame = batch.frame
        stamps = [datetime.fromtimestamp(s.wall_start + t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f") for t in batch.emit_t]
        frame["Timestamp"] = stamps  # event time = when the flow arrived in the session

        results = self.predictor.predict_frame(frame, row_offset=s.processed, feature_rows_remaining=s.feature_budget)
        done = time.monotonic() - s.mono_start
        s.feature_budget -= sum(1 for r in results if r["features"] is not None)
        phases = {p.idx: p for p in s.source.planned_phases()}
        benign = self.predictor.store.benign_label

        for r, emit_t, pidx in zip(results, batch.emit_t, batch.phase_idx):
            latency_ms = (done - float(emit_t)) * 1000.0
            s.latencies.append(latency_ms)
            sec = int(emit_t)
            bucket = s.series.setdefault(sec, [0, 0])
            flagged = r["is_suspicious"]
            bucket[1 if flagged else 0] += 1
            s.risk[r["risk_level"]] += 1
            s.pred_counts[r["predicted_class"]] += 1
            if flagged:
                s.suspicious += 1
            if r["requires_review"]:
                s.needs_review += 1

            truth = r.get("ground_truth_label")
            if truth:
                s.confusion[(truth, r["predicted_class"])] += 1
                truth_attack = truth != benign
                key = ("tp" if flagged else "fn") if truth_attack else ("fp" if flagged else "tn")
                s.truth[key] += 1

            if pidx >= 0 and pidx in phases:
                st = s.phase_stats[int(pidx)]
                st["flows"] += 1
                if flagged:
                    st["flagged"] += 1
                    if r["predicted_class"] == phases[int(pidx)].label:
                        st["correct_category"] += 1
                    if st["first_detection_s"] is None:
                        st["first_detection_s"] = round(max(0.0, done - phases[int(pidx)].start), 3)

            if flagged or r["requires_review"]:
                alert = {
                    "id": r["record_id"], "time": r["flow_timestamp"], "predicted_class": r["predicted_class"],
                    "confidence": r["confidence"], "risk_level": r["risk_level"], "requires_review": r["requires_review"],
                    "is_suspicious": flagged, "rule_id": r["risk_rule_id"], "truth_label": truth,
                    "src_ip": r.get("src_ip"), "dst_ip": r.get("dst_ip"), "latency_ms": round(latency_ms, 1),
                }
                s.recent_alerts.appendleft(alert)
                if len(s.pending_alerts) < MAX_ALERTS_PER_TICK:
                    s.pending_alerts.append(alert)
                else:
                    s.suppressed_alerts += 1

        s.processed += len(results)
        s.throughput.append((done, len(results)))
        self.repo.insert_records(s.scan_id, results)
        self.repo.update_scan(s.scan_id, rows_processed=s.processed)
        s.batch_ms.append((time.monotonic() - t_begin) * 1000.0)

    # --------------------------------------------------------------- snapshots
    def _idle_snapshot(self) -> dict:
        return {"state": "idle", "session": None, "totals": None, "rate": 0.0, "latency_ms": None, "series": [],
                "truth": None, "phases": [], "recent_alerts": [], "processing_ms": None, "limits": self._limits(),
                "simulator": {"available": self.pool.available, "error": self.pool.error}}

    def _limits(self) -> dict:
        st = self.settings
        return {"max_rate": st.max_realtime_rate, "max_seconds": st.max_session_seconds, "max_records": st.max_realtime_records}

    def _truth_metrics(self, s: _Session) -> dict | None:
        t = s.truth
        n = sum(t.values())
        if n == 0:
            return None
        def div(a, b):
            return a / b if b else None
        p, r = div(t["tp"], t["tp"] + t["fp"]), div(t["tp"], t["tp"] + t["fn"])
        return {**t, "flows_with_truth": n, "precision": p, "recall": r, "false_positive_rate": div(t["fp"], t["fp"] + t["tn"]),
                "f1": (2 * p * r / (p + r)) if p and r else None}

    def _build_snapshot(self, s: _Session) -> dict:
        now = s.elapsed
        cur = int(now)
        series = []
        for sec in range(max(0, cur - SERIES_SECONDS + 1), cur + 1):
            n, f = s.series.get(sec, [0, 0])
            series.append({"t": sec, "normal": n, "suspicious": f})
        while s.throughput and s.throughput[0][0] < (time.monotonic() - s.mono_start) - 2.0:
            s.throughput.popleft()
        rate = sum(n for _, n in s.throughput) / 2.0 if s.state == "running" else 0.0
        lat = list(s.latencies)
        phases = []
        for p in s.source.planned_phases():
            st = s.phase_stats.get(p.idx, {})
            status = "pending" if now < p.start else ("active" if now < p.end else "done")
            if s.state != "running" and status == "active":
                status = "done"
            phases.append({"idx": p.idx, "label": p.label, "start": p.start, "duration": p.duration, "rate": p.rate,
                           "status": status, **st,
                           "recall": (st["flagged"] / st["flows"]) if st.get("flows") else None})
        return {
            "state": s.state,
            "session": {"id": s.id, "scan_id": s.scan_id, "mode": s.mode, "name": s.name, "description": s.source.description,
                        "started_at": s.started_at, "elapsed_s": round(now, 2), "duration_s": s.source.duration or s.max_seconds,
                        "scenario": s.scenario, "model_version": self.predictor.store.version,
                        "stop_reason": s.stop_reason, "error": s.error},
            "totals": {"flows": s.processed, "suspicious": s.suspicious, "normal": s.processed - s.suspicious,
                       "needs_review": s.needs_review, "risk": dict(s.risk)},
            "rate": round(rate, 1),
            "latency_ms": ({"p50": _pct(lat, 50), "p95": _pct(lat, 95), "max": max(lat), "mean": float(np.mean(lat)), "samples": len(lat)}
                           if lat else None),
            "processing_ms": ({"mean": float(np.mean(s.batch_ms)), "max": max(s.batch_ms)} if s.batch_ms else None),
            "series": series,
            "truth": self._truth_metrics(s),
            "phases": phases,
            "recent_alerts": list(s.recent_alerts)[:50],
            "limits": self._limits(),
            "simulator": {"available": self.pool.available, "error": self.pool.error},
        }

    def _publish(self, s: _Session, event_type: str) -> None:
        snap = self._build_snapshot(s)
        self._cache = snap
        new, suppressed = s.pending_alerts, s.suppressed_alerts
        s.pending_alerts, s.suppressed_alerts = [], 0
        self._broadcast({"type": event_type, **snap, "new_alerts": new, "suppressed_alerts": suppressed})

    def _broadcast(self, event: dict) -> None:
        with self._sub_lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(self._offer, q, event)
            except RuntimeError:  # loop already closed
                self.unsubscribe(q)

    @staticmethod
    def _offer(q: asyncio.Queue, event: dict) -> None:
        if q.full():
            try:
                q.get_nowait()  # slow consumer: drop the oldest update, never block the engine
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)

    # ---------------------------------------------------------------- finalize
    def _finalize(self, s: _Session) -> None:
        try:
            s.state = "failed" if s.error else ("finished" if s.stop_reason == "completed" else "stopped")
            lat = list(s.latencies)
            labels = sorted({k[0] for k in s.confusion} | {k[1] for k in s.confusion})
            comparison = None
            if labels:
                idx = {l: i for i, l in enumerate(labels)}
                cm = np.zeros((len(labels), len(labels)), dtype=np.int64)
                for (t, p), n in s.confusion.items():
                    cm[idx[t], idx[p]] += n
                comparison = evaluate_from_confusion(
                    cm, labels, "ground truth known to the simulation or replay source (live session)")
                comparison["caveat"] = (
                    "Scored against labels the source knew. The model never saw them. For simulated scenarios the flows come from "
                    "held-out data, but repeated sampling means a small pool is reused many times.")
            duration = max(s.elapsed, 1e-9)
            snap = self._build_snapshot(s)
            summary = {
                "records_analyzed": s.processed,
                "predicted_class_counts": {},
                "risk_level_counts": dict(s.risk),
                "duration_seconds": round(s.elapsed, 2),
                "label_comparison": comparison,
                "realtime": {
                    "mode": s.mode, "stop_reason": s.stop_reason, "scenario": s.scenario,
                    "avg_throughput_flows_per_s": round(s.processed / duration, 1),
                    "latency_ms": snap["latency_ms"], "processing_ms": snap["processing_ms"],
                    "phases": snap["phases"], "truth": snap["truth"],
                    "latency_note": "Latency is flow arrival to prediction complete, including up to one 100 ms micro-batch wait. Percentiles use the last 5,000 flows.",
                },
            }
            summary["predicted_class_counts"] = dict(s.pred_counts)
            self.repo.update_scan(
                s.scan_id, status="failed" if s.error else "completed", finished_at=utcnow(), rows_total=s.processed,
                rows_processed=s.processed, error=s.error, summary=summary)
            self._cache = snap
            self._broadcast({"type": "status", **snap, "new_alerts": s.pending_alerts, "suppressed_alerts": s.suppressed_alerts})
        except Exception:  # noqa: BLE001
            log.exception("Failed to finalize session")
