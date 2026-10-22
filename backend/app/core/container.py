"""Wires the long-lived services together once at startup."""
from __future__ import annotations

from dataclasses import dataclass

from ..database.db import Database
from ..database.repository import Repository
from ..ml.model_store import ModelStore
from ..risk.engine import RiskEngine
from ..services.analysis import AnalysisService
from ..services.prediction import Predictor
from ..services.realtime import RealtimeEngine
from ..services.simulation import SimulationPool
from .config import Settings


@dataclass
class Container:
    settings: Settings
    db: Database
    repo: Repository
    store: ModelStore
    risk: RiskEngine
    predictor: Predictor
    analysis: AnalysisService
    pool: SimulationPool
    realtime: RealtimeEngine
    db_warning: str | None = None


def build_container(settings: Settings) -> Container:
    settings.ensure_dirs()
    db_warning = None
    db = Database(settings.database_path, settings.database_url)
    try:
        db.init()
    except Exception as exc:  # noqa: BLE001 - keep the site up and say so, rather than crash-looping
        if not settings.database_url:
            raise
        import logging
        logging.getLogger("nid").exception("Postgres is unreachable; using temporary local storage instead")
        db_warning = f"Postgres unreachable ({type(exc).__name__}); using temporary local storage that is lost on restart."
        db = Database(settings.database_path, None)
        db.init()
    repo = Repository(db)
    repo.fail_interrupted_scans()
    store = ModelStore(settings.model_path, settings.model_metadata_path, settings.evaluation_path)
    store.load()
    risk = RiskEngine.from_file(settings.risk_rules_path)
    predictor = Predictor(store, risk)
    analysis = AnalysisService(settings, repo, predictor)
    pool = SimulationPool.load(settings.pool_path, store.version) if store.loaded else SimulationPool(None, None, store.error)
    realtime = RealtimeEngine(settings, repo, predictor, pool)
    return Container(settings, db, repo, store, risk, predictor, analysis, pool, realtime, db_warning)
