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


def build_container(settings: Settings) -> Container:
    settings.ensure_dirs()
    db = Database(settings.database_path, settings.database_url)
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
    return Container(settings, db, repo, store, risk, predictor, analysis, pool, realtime)
