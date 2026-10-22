"""Real-time detection sessions: controlled simulation, capture replay and external feed."""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..core.container import Container
from ..schemas.api import IngestIn, SessionStart
from ..services.prediction import MissingFeaturesError
from ..services.realtime import SessionConflict, SessionError
from ..services.simulation import LiveSource, Phase, ReplaySource, Scenario, ScenarioSource, build_presets, validate_scenario
from .deps import get_container, require_model

router = APIRouter(prefix="/api/realtime", tags=["real-time"])


@router.get("/scenarios")
def scenarios(c: Container = Depends(get_container)):
    """Preset scenarios plus what the simulator can produce. Nothing is sent on any network."""
    return {
        "available": c.pool.available,
        "error": c.pool.error,
        "classes": c.pool.classes,
        "pool_counts": c.pool.counts,
        "presets": build_presets(c.pool.classes) if c.pool.available else [],
        "limits": {"max_rate": c.settings.max_realtime_rate, "max_seconds": c.settings.max_session_seconds,
                   "max_records": c.settings.max_realtime_records},
        "note": ("The simulator composes flow records from labelled flows the model was not trained on. It does not generate "
                 "or transmit network traffic. Ground truth is known to the simulator and used only for scoring."),
        "replayable_scans": [
            {"id": s["id"], "filename": s["filename"], "rows": s["rows_total"], "label_column_present": bool((s.get("validation") or {}).get("label_column_present"))}
            for s in c.repo.list_scans(200) if s["source"] == "upload" and s["status"] in ("uploaded", "completed")
        ],
    }


@router.get("/status")
def status(c: Container = Depends(get_container)):
    return c.realtime.snapshot()


@router.post("/sessions", status_code=201)
def start_session(body: SessionStart, c: Container = Depends(get_container)):
    require_model(c)
    st = c.settings
    if body.mode == "simulation":
        if body.scenario is None:
            raise HTTPException(422, "A scenario is required for simulation mode.")
        sc_in = body.scenario
        scenario = Scenario(
            name=sc_in.name.strip() or "Custom scenario",
            seed=sc_in.seed if sc_in.seed is not None else random.randint(1, 2**31 - 1),
            duration=sc_in.duration_seconds, baseline_rate=sc_in.baseline_rate,
            phases=[Phase(i, p.label, p.start, p.duration, p.rate) for i, p in enumerate(sorted(sc_in.phases, key=lambda p: p.start))])
        problems = validate_scenario(scenario, c.pool, st.max_realtime_rate, st.max_session_seconds)
        if problems:
            raise HTTPException(422, {"message": "The scenario is not valid.", "problems": problems})
        source, name, scenario_dict = ScenarioSource(scenario, c.pool), scenario.name, scenario.to_dict()
        max_seconds = None
    elif body.mode == "replay":
        if body.replay is None:
            raise HTTPException(422, "Replay settings are required for replay mode.")
        scan = c.repo.get_scan(body.replay.scan_id)
        path = c.repo.get_scan_file(body.replay.scan_id) if scan else None
        if scan is None or scan["source"] != "upload" or not path or not Path(path).exists():
            raise HTTPException(404, "That upload is not available for replay.")
        if not 0 < body.replay.rate <= st.max_realtime_rate:
            raise HTTPException(422, f"Replay rate must be between 0 and {st.max_realtime_rate} flows per second.")
        source = ReplaySource(Path(path), body.replay.rate, body.replay.loop, scan["filename"] or "upload")
        name, scenario_dict = scan["filename"] or "upload", None
        max_seconds = min(body.max_duration_seconds or st.max_session_seconds, st.max_session_seconds)
        source.duration = None
    else:
        max_seconds = min(body.max_duration_seconds or st.max_session_seconds, st.max_session_seconds)
        source, name, scenario_dict = LiveSource(max_seconds), "External feed", None
    try:
        return c.realtime.start(source, mode=body.mode, name=name, scenario=scenario_dict, max_seconds=max_seconds)
    except SessionConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/sessions/stop")
def stop_session(c: Container = Depends(get_container)):
    try:
        return c.realtime.stop()
    except SessionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/ingest")
def ingest(body: IngestIn, c: Container = Depends(get_container)):
    """Push flows (feature name -> value) into a running 'live' session. They are scored within about 100 ms."""
    require_model(c)
    try:
        accepted = c.realtime.ingest(body.flows)
    except SessionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MissingFeaturesError as exc:
        raise HTTPException(422, {"message": "A flow does not match the model's feature schema.", "problems": [str(exc)]}) from exc
    if accepted < len(body.flows):
        raise HTTPException(429, f"Ingest queue full: accepted {accepted} of {len(body.flows)} flows. Slow down and retry the rest.")
    return {"accepted": accepted}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/stream")
async def stream(request: Request, c: Container = Depends(get_container)):
    """Server-Sent Events: a full state snapshot on connect, then an update every 500 ms while a session runs."""
    engine = c.realtime
    q = engine.subscribe()

    async def generate():
        try:
            yield "retry: 2000\n\n"
            yield _sse("snapshot", {"type": "snapshot", **engine.snapshot(), "new_alerts": []})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event["type"], event)
        finally:
            engine.unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
