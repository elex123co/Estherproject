"""Rule-based risk assessment, kept separate from the machine-learning model.

Inputs: predicted class, model confidence (optional), record-level evidence.
Output: a risk level plus the rule id and a human-readable reason for every assessment.

Design points
- Severity comes from the predicted attack category's rule, optionally raised by an explicit
  escalation rule that needs evidence in the record (not confidence alone).
- Low model confidence never creates or raises severity. It caps the level and marks the record
  "requires review".
- When there is no basis for a severity, the level is "Needs review" instead of an invented score.
"""
from __future__ import annotations

import json
import math
import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

LEVEL_ORDER = ["None", "Needs review", "Low", "Medium", "High", "Critical"]
SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq}


@dataclass
class RiskAssessment:
    level: str
    requires_review: bool
    rule_id: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


class RiskEngine:
    def __init__(self, rules: dict):
        self.rules = rules
        self.benign_label = rules.get("benign_label", "BENIGN")

    @classmethod
    def from_file(cls, path: Path) -> "RiskEngine":
        with open(path, "r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    @property
    def version(self) -> str:
        return str(self.rules.get("version", "unversioned"))

    def assess(
        self,
        predicted_class: str,
        confidence: float | None,
        evidence_row: Mapping[str, Any] | None = None,
        imputed_fraction: float = 0.0,
    ) -> RiskAssessment:
        evidence_row = evidence_row or {}
        low_conf = self.rules.get("low_confidence_threshold", 0.6)
        max_imputed = self.rules.get("max_imputed_fraction", 0.2)
        too_imputed = imputed_fraction > max_imputed
        imputed_note = (
            f" {imputed_fraction:.0%} of the model features were missing or invalid and were imputed."
            if too_imputed
            else ""
        )

        # ---- normal traffic -------------------------------------------------------------
        if predicted_class == self.benign_label:
            threshold = self.rules.get("benign_review_confidence_below")
            if confidence is not None and threshold is not None and confidence < threshold:
                return RiskAssessment(
                    "Needs review",
                    True,
                    "BENIGN-LOW-CONFIDENCE",
                    f"Predicted normal, but model confidence {confidence:.2f} is below {threshold:.2f}. "
                    "Result is uncertain and not treated as clean." + imputed_note,
                    {"confidence": round(confidence, 4)},
                )
            if too_imputed:
                return RiskAssessment(
                    "Needs review", True, "BENIGN-INCOMPLETE-DATA",
                    "Predicted normal, but the record has too many missing or invalid values to trust." + imputed_note,
                    {"imputed_fraction": round(imputed_fraction, 4)},
                )
            return RiskAssessment("None", False, "BENIGN", "Predicted normal. No risk rule applies.")

        # ---- suspicious traffic ---------------------------------------------------------
        rule = self.rules.get("category_rules", {}).get(predicted_class)
        if rule is None:
            default = self.rules["default_rule"]
            return RiskAssessment(
                default["level"], True, default["rule_id"], default["reason"] + imputed_note
            )

        level = rule["level"]
        rule_id = rule["rule_id"]
        reasons = [rule["reason"]]
        evidence: dict[str, Any] = {}
        requires_review = False

        for esc in self.rules.get("escalations", []):
            if predicted_class not in esc.get("categories", []):
                continue
            if confidence is None or confidence < esc.get("min_confidence", 0.0):
                continue
            satisfied, used = self._conditions_met(esc.get("conditions", []), evidence_row)
            if satisfied and SEVERITY_RANK[esc["raise_to"]] > SEVERITY_RANK.get(level, 0):
                level = esc["raise_to"]
                rule_id = esc["rule_id"]
                evidence.update(used)
                detail = ", ".join(f"{k}={v:g}" for k, v in used.items())
                reasons.append(
                    f"Escalated to {level} by {esc['rule_id']}: confidence {confidence:.2f} >= "
                    f"{esc.get('min_confidence', 0):.2f} and record evidence ({detail}) meets the rule."
                )

        if confidence is not None and confidence < low_conf:
            cap = self.rules.get("confidence_cap_level", "Medium")
            if SEVERITY_RANK[level] > SEVERITY_RANK[cap]:
                level = cap
            requires_review = True
            rule_id = f"{rule_id}+LOW-CONFIDENCE"
            reasons.append(
                f"Model confidence {confidence:.2f} is below {low_conf:.2f}, so severity is capped at {cap} "
                "and the classification needs analyst verification."
            )
            evidence["confidence"] = round(confidence, 4)

        if too_imputed:
            requires_review = True
            reasons.append(imputed_note.strip())
            evidence["imputed_fraction"] = round(imputed_fraction, 4)

        return RiskAssessment(level, requires_review, rule_id, " ".join(reasons), evidence)

    @staticmethod
    def _conditions_met(conditions: list[dict], row: Mapping[str, Any]) -> tuple[bool, dict[str, float]]:
        used: dict[str, float] = {}
        for cond in conditions:
            raw = row.get(cond["feature"])
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return False, {}
            if math.isnan(value) or math.isinf(value):
                return False, {}
            if not OPS[cond["op"]](value, cond["value"]):
                return False, {}
            used[cond["feature"]] = value
        return True, used
