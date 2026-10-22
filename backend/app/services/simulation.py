"""Controlled simulation environment.

Everything here happens in-process. No packets are generated or sent on any network.

The simulator composes *flow records* (rows of flow features), not traffic:
- A SimulationPool holds labelled flows saved at training time from splits the model never fitted on.
- A Scenario is a seeded, repeatable plan: a benign baseline plus timed attack phases with set rates.
- Because the simulator knows each flow's true label, the real-time engine can measure live precision,
  recall, false alarms and time-to-detection. The model never sees the label.

Sources (all feed the same real-time pipeline): ScenarioSource, ReplaySource (an uploaded labelled
capture replayed at a controlled rate) and LiveSource (flows pushed to the ingest endpoint).
"""
from __future__ import annotations

import logging
import queue
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ..ml.data_loader import iter_csv_chunks
from ..ml.schema import BENIGN_LABEL

log = logging.getLogger("nid.simulation")

# Addresses for simulated hosts come from reserved ranges so they can never be mistaken for real ones:
# benign clients/servers use RFC 1918 space, attackers use the RFC 5737 documentation ranges.
BENIGN_CLIENTS = [f"192.168.10.{i}" for i in range(2, 42)]
SERVERS = ["10.20.0.10", "10.20.0.11", "10.20.0.12"]
ATTACKER_NET_SINGLE = "198.51.100.{}"
ATTACKER_NET_DISTRIBUTED = "203.0.113.{}"


@dataclass
class Phase:
    idx: int
    label: str
    start: float
    duration: float
    rate: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Scenario:
    name: str
    seed: int
    duration: float
    baseline_rate: float
    phases: list[Phase] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "seed": self.seed, "duration_seconds": self.duration,
                "baseline_rate": self.baseline_rate, "phases": [asdict(p) for p in self.phases]}


@dataclass
class Batch:
    frame: pd.DataFrame           # feature columns + Label (ground truth, if known) + context columns
    emit_t: np.ndarray            # when each flow "arrived", seconds since session start
    phase_idx: np.ndarray         # scenario phase of each flow, -1 for baseline/none


class SimulationPool:
    def __init__(self, frame: pd.DataFrame | None, model_version: str | None, error: str | None = None):
        self.frame = frame
        self.model_version = model_version
        self.error = error
        self._by_class: dict[str, pd.DataFrame] = {}
        if frame is not None:
            for label, rows in frame.groupby("Label"):
                self._by_class[str(label)] = rows.reset_index(drop=True)

    @classmethod
    def load(cls, path: Path, expected_model_version: str | None) -> "SimulationPool":
        try:
            if not path.exists():
                return cls(None, None, f"No simulation pool at {path}. Retrain the model to create one.")
            bundle = joblib.load(path)
            if expected_model_version and bundle.get("model_version") != expected_model_version:
                return cls(None, None, "The simulation pool belongs to a different model version. Retrain to regenerate it.")
            return cls(bundle["frame"], bundle.get("model_version"))
        except Exception as exc:  # noqa: BLE001
            return cls(None, None, f"{type(exc).__name__}: {exc}")

    @property
    def available(self) -> bool:
        return self.frame is not None and BENIGN_LABEL in self._by_class

    @property
    def classes(self) -> list[str]:
        return sorted(self._by_class)

    @property
    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in sorted(self._by_class.items())}

    def sample(self, label: str, n: int, rng: np.random.Generator) -> pd.DataFrame:
        rows = self._by_class[label]
        return rows.iloc[rng.integers(0, len(rows), size=n)]


# ----------------------------------------------------------------------------- presets
def build_presets(classes: list[str]) -> list[dict]:
    """Preset scenarios restricted to attack classes that exist in the pool."""
    have = set(classes)

    def ph(label: str, start: float, duration: float, rate: float):
        return {"label": label, "start": start, "duration": duration, "rate": rate}

    def keep(phases):
        return [p for p in phases if p["label"] in have]

    flood = "DDoS" if "DDoS" in have else ("DoS Hulk" if "DoS Hulk" in have else None)
    presets = [
        {"id": "baseline", "name": "Baseline (normal traffic only)",
         "description": "No attacks. Use it to measure false alarms on clean traffic.",
         "scenario": {"name": "Baseline", "seed": 1, "duration_seconds": 60, "baseline_rate": 40, "phases": []}},
        {"id": "recon-flood", "name": "Reconnaissance then flood",
         "description": "A port scan, then a denial-of-service flood against a server.",
         "scenario": {"name": "Reconnaissance then flood", "seed": 7, "duration_seconds": 90, "baseline_rate": 30,
                      "phases": keep([ph("PortScan", 15, 15, 60)] + ([ph(flood, 45, 25, 150)] if flood else []))}},
        {"id": "brute-force", "name": "Credential brute-force",
         "description": "FTP, then SSH password guessing.",
         "scenario": {"name": "Credential brute-force", "seed": 11, "duration_seconds": 90, "baseline_rate": 30,
                      "phases": keep([ph("FTP-Patator", 15, 25, 40), ph("SSH-Patator", 50, 25, 40)])}},
        {"id": "full-campaign", "name": "Multi-stage campaign",
         "description": "Scan, flood, botnet and infiltration phases, with quiet gaps between them.",
         "scenario": {"name": "Multi-stage campaign", "seed": 42, "duration_seconds": 150, "baseline_rate": 40,
                      "phases": keep([ph("PortScan", 10, 15, 60)] + ([ph(flood, 35, 20, 200)] if flood else []) +
                                     [ph("DoS Hulk", 65, 15, 120), ph("Bot", 90, 20, 30), ph("Infiltration", 120, 15, 8)])}},
    ]
    for p in presets:
        # de-duplicate when 'flood' fell back to DoS Hulk
        seen, uniq = set(), []
        for phase in p["scenario"]["phases"]:
            key = (phase["label"], phase["start"])
            if key not in seen:
                seen.add(key)
                uniq.append(phase)
        p["scenario"]["phases"] = uniq
    return presets


def validate_scenario(sc: Scenario, pool: SimulationPool, max_rate: int, max_seconds: int) -> list[str]:
    problems: list[str] = []
    if not 5 <= sc.duration <= max_seconds:
        problems.append(f"Duration must be between 5 and {max_seconds} seconds.")
    if not 0 <= sc.baseline_rate <= max_rate:
        problems.append(f"Baseline rate must be between 0 and {max_rate} flows per second.")
    if len(sc.phases) > 20:
        problems.append("At most 20 attack phases are allowed.")
    for p in sc.phases:
        if p.label == BENIGN_LABEL or p.label not in pool.classes:
            problems.append(f"Phase {p.idx + 1}: '{p.label}' is not an attack class available in the simulation pool.")
        if p.start < 0 or p.duration <= 0 or p.end > sc.duration + 1e-9:
            problems.append(f"Phase {p.idx + 1} ({p.label}) must lie within the scenario duration.")
        if not 0 < p.rate <= max_rate:
            problems.append(f"Phase {p.idx + 1} ({p.label}) rate must be between 0 and {max_rate} flows per second.")
    if not problems:
        points = [0.0] + [p.start for p in sc.phases]
        peak = max(sc.baseline_rate + sum(p.rate for p in sc.phases if p.start <= t < p.end) for t in points)
        if peak > max_rate:
            problems.append(f"Combined peak rate {peak:.0f} flows/s exceeds the limit of {max_rate}.")
    if not pool.available:
        problems.append(pool.error or "The simulation pool is not available.")
    return problems


# ----------------------------------------------------------------------------- sources
class Source:
    mode = "base"
    description = ""
    duration: float | None = None
    mono_start: float = 0.0

    def planned_phases(self) -> list[Phase]:
        return []

    def next_batch(self, t0: float, t1: float) -> Batch | None:  # pragma: no cover - interface
        raise NotImplementedError

    def finished(self, t: float) -> bool:
        return self.duration is not None and t >= self.duration


class ScenarioSource(Source):
    mode = "simulation"

    def __init__(self, scenario: Scenario, pool: SimulationPool):
        self.scenario = scenario
        self.pool = pool
        self.duration = scenario.duration
        self.rng = np.random.default_rng(scenario.seed)
        self.description = f"Simulated scenario '{scenario.name}' (seed {scenario.seed})"
        # Fixed attacker identities per phase so repeated runs look the same.
        self._attackers = {
            p.idx: (
                [ATTACKER_NET_DISTRIBUTED.format(int(self.rng.integers(2, 250))) for _ in range(30)]
                if p.label == "DDoS" else [ATTACKER_NET_SINGLE.format(10 + p.idx)]
            )
            for p in scenario.phases
        }
        self._victim = {p.idx: SERVERS[p.idx % len(SERVERS)] for p in scenario.phases}
        self._cell = 0

    def planned_phases(self) -> list[Phase]:
        return self.scenario.phases

    CELL = 0.1  # scenario time is generated on a fixed grid so a seed always yields the same flows

    def next_batch(self, t0: float, t1: float) -> Batch | None:
        batches = []
        while True:
            a = self._cell * self.CELL
            b = min(a + self.CELL, self.scenario.duration)
            if a >= self.scenario.duration or b > t1 + 1e-9:
                break  # cell has not "arrived" yet (or the scenario is over)
            batch = self._generate_cell(self._cell, a, b)
            self._cell += 1
            if batch is not None:
                batches.append(batch)
        if not batches:
            return None
        if len(batches) == 1:
            return batches[0]
        return Batch(pd.concat([b.frame for b in batches], ignore_index=True),
                     np.concatenate([b.emit_t for b in batches]), np.concatenate([b.phase_idx for b in batches]))

    def finished(self, t: float) -> bool:
        return self._cell * self.CELL >= self.scenario.duration

    def _generate_cell(self, k: int, a: float, b: float) -> Batch | None:
        sc = self.scenario
        rng = np.random.default_rng([sc.seed, k])
        width = b - a
        parts, phase_ids, src_ips, dst_ips = [], [], [], []

        def add(label: str, n: int, phase: int, sources: list[str] | None, dst: str | None):
            if n <= 0:
                return
            parts.append(self.pool.sample(label, n, rng))
            phase_ids.append(np.full(n, phase))
            if sources is None:
                src_ips.extend(rng.choice(BENIGN_CLIENTS, size=n))
                dst_ips.extend(rng.choice(SERVERS, size=n))
            else:
                src_ips.extend(rng.choice(sources, size=n))
                dst_ips.extend([dst] * n)

        add(BENIGN_LABEL, int(rng.poisson(sc.baseline_rate * width)), -1, None, None)
        for p in sc.phases:
            overlap = min(b, p.end) - max(a, p.start)
            if overlap > 0:
                add(p.label, int(rng.poisson(p.rate * overlap)), p.idx, self._attackers[p.idx], self._victim[p.idx])
        if not parts:
            return None
        frame = pd.concat(parts, ignore_index=True)
        order = rng.permutation(len(frame))  # interleave classes within the cell
        frame = frame.iloc[order].reset_index(drop=True)
        frame["Source IP"] = np.asarray(src_ips, dtype=object)[order]
        frame["Destination IP"] = np.asarray(dst_ips, dtype=object)[order]
        emit_t = np.sort(rng.uniform(a, b, size=len(frame)))
        return Batch(frame, emit_t, np.concatenate(phase_ids)[order])


class ReplaySource(Source):
    """Replays a stored, uploaded capture at a fixed rate, preserving row order."""
    mode = "replay"

    def __init__(self, path: Path, rate: float, loop: bool, name: str, chunk_rows: int = 2000):
        self.path, self.rate, self.loop = path, rate, loop
        self.chunk_rows = chunk_rows
        self.description = f"Replay of '{name}' at {rate:g} flows/s" + (" (looping)" if loop else "")
        self._iter = iter_csv_chunks(path, chunk_rows)
        self._buffer = pd.DataFrame()
        self._carry = 0.0
        self._exhausted = False

    def _refill(self) -> None:
        if len(self._buffer) or self._exhausted:
            return
        try:
            self._buffer = next(self._iter)
        except StopIteration:
            if self.loop:
                self._iter = iter_csv_chunks(self.path, self.chunk_rows)
                try:
                    self._buffer = next(self._iter)
                except StopIteration:
                    self._exhausted = True
            else:
                self._exhausted = True

    def next_batch(self, t0: float, t1: float) -> Batch | None:
        self._carry += self.rate * (t1 - t0)
        n = int(self._carry)
        if n <= 0:
            return None
        self._carry -= n
        taken = []
        while n > 0:
            self._refill()
            if self._buffer.empty:
                break
            part = self._buffer.iloc[:n]
            self._buffer = self._buffer.iloc[n:]
            n -= len(part)
            taken.append(part)
        if not taken:
            return None
        frame = pd.concat(taken, ignore_index=True)
        emit_t = np.sort(np.random.default_rng().uniform(t0, t1, size=len(frame)))
        return Batch(frame, emit_t, np.full(len(frame), -1))

    def finished(self, t: float) -> bool:
        return self._exhausted and self._buffer.empty


class LiveSource(Source):
    """Flows pushed by an external exporter through the ingest endpoint."""
    mode = "live"

    def __init__(self, max_seconds: float, capacity: int = 20000):
        self.duration = max_seconds
        self.description = "External feed (flows posted to /api/realtime/ingest)"
        self.queue: queue.Queue = queue.Queue(maxsize=capacity)

    def push(self, flows: list[dict[str, Any]]) -> int:
        received = time.monotonic() - self.mono_start
        accepted = 0
        for flow in flows:
            try:
                self.queue.put_nowait((flow, received))
                accepted += 1
            except queue.Full:
                break
        return accepted

    def next_batch(self, t0: float, t1: float) -> Batch | None:
        items = []
        while len(items) < 2000:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                break
        if not items:
            return None
        frame = pd.DataFrame([i[0] for i in items])
        frame.columns = [str(c).strip() for c in frame.columns]
        return Batch(frame, np.array([i[1] for i in items]), np.full(len(items), -1))
