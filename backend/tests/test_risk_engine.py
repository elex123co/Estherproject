"""Unit tests for the rule-based risk engine (no model needed)."""
from pathlib import Path

import pytest

from app.risk.engine import RiskEngine

RULES = Path(__file__).resolve().parents[1] / "app" / "risk" / "rules.json"


@pytest.fixture(scope="module")
def engine():
    return RiskEngine.from_file(RULES)


def test_benign_confident_is_none(engine):
    a = engine.assess("BENIGN", 0.99)
    assert a.level == "None" and not a.requires_review


def test_benign_low_confidence_needs_review_not_clean(engine):
    a = engine.assess("BENIGN", 0.45)
    assert a.level == "Needs review" and a.requires_review


def test_category_sets_level_and_keeps_reason(engine):
    a = engine.assess("PortScan", 0.99)
    assert a.level == "Low"
    assert a.rule_id == "CAT-RECON" and a.reason


def test_high_confidence_alone_does_not_make_critical(engine):
    # A near-certain low-impact prediction must stay Low.
    a = engine.assess("PortScan", 1.0, {"Flow Packets/s": 1e9})
    assert a.level == "Low"


def test_dos_escalates_only_with_confidence_and_evidence(engine):
    base = engine.assess("DDoS", 0.95, {"Flow Packets/s": 10.0})
    assert base.level == "High"
    escalated = engine.assess("DDoS", 0.95, {"Flow Packets/s": 120000.0})
    assert escalated.level == "Critical" and escalated.rule_id == "ESC-DOS-VOLUME"
    unsure = engine.assess("DDoS", 0.7, {"Flow Packets/s": 120000.0})
    assert unsure.level == "High"


def test_missing_evidence_does_not_escalate(engine):
    a = engine.assess("DDoS", 0.99, {"Flow Packets/s": float("nan")})
    assert a.level == "High"


def test_low_confidence_caps_severity_and_requires_review(engine):
    a = engine.assess("Infiltration", 0.4)
    assert a.level == "Medium" and a.requires_review and "LOW-CONFIDENCE" in a.rule_id


def test_unmapped_category_is_needs_review(engine):
    a = engine.assess("Some New Attack", 0.99)
    assert a.level == "Needs review" and a.requires_review


def test_no_probability_available_skips_confidence_rules(engine):
    a = engine.assess("DDoS", None, {"Flow Packets/s": 120000.0})
    assert a.level == "High"  # escalation needs a confidence value


def test_heavily_imputed_record_requires_review(engine):
    a = engine.assess("Bot", 0.95, {}, imputed_fraction=0.5)
    assert a.requires_review
