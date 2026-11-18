"""건강검진 수치 판정 엔진. 기준값은 코드가 아니라 app/data/nhis_criteria.json에서 읽는다."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

CRITERIA_JSON = Path(__file__).resolve().parents[1] / "data" / "nhis_criteria.json"
_OPERATORS = {
    "gte": lambda v, t: v >= t,
    "gt": lambda v, t: v > t,
    "lte": lambda v, t: v <= t,
    "lt": lambda v, t: v < t,
}


@lru_cache(maxsize=1)
def _load_criteria() -> Dict[str, Any]:
    return json.loads(CRITERIA_JSON.read_text(encoding="utf-8"))


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display(value: float) -> Any:
    return int(value) if value.is_integer() else value


def _condition_met(cond: Dict[str, Any], values: Dict[str, float]) -> bool:
    value = values.get(cond["input"])
    if value is None:
        return False
    return all(op(value, cond[name]) for name, op in _OPERATORS.items() if name in cond)


def _pick_band(bands: List[Dict[str, Any]], values: Dict[str, float]) -> Dict[str, Any]:
    """위험도가 높은 구간부터 차례로 검사해 처음 맞는 구간을 고른다. 조건이 없는 구간은 기본값이다."""
    for band in bands:
        conditions = band.get("any")
        if conditions is None or any(_condition_met(c, values) for c in conditions):
            return band
    return bands[-1]


def evaluate_metrics(metrics: Dict[str, Any], gender: str = "unknown") -> Dict[str, Any]:
    criteria = _load_criteria()
    evaluations: List[Dict[str, Any]] = []
    departments: List[str] = []
    confirm_exam_eligible: List[str] = []

    for key, spec in criteria["metrics"].items():
        values = {name: _to_float(metrics.get(name)) for name in spec["inputs"]}
        if any(v is None for v in values.values()):
            continue

        spec = {**spec, **spec.get("by_gender", {}).get(gender, {})}
        band = _pick_band(spec["bands"], values)
        shown = {name: _display(v) for name, v in values.items()}
        value = spec["value_format"].format(**shown) if "value_format" in spec else next(iter(shown.values()))

        recommend = band.get("recommend", [])
        evaluations.append(
            {
                "key": key,
                "item": spec["item"],
                "value": value,
                "unit": spec["unit"],
                "reference": spec["reference"],
                "status": band["status"],
                "severity": band["severity"],
                "department": " / ".join(recommend) if recommend else "-",
                "source": "국민건강보험공단 일반건강검진 판정기준",
            }
        )
        for dept in recommend:
            if dept not in departments:
                departments.append(dept)
        label = band.get("confirm_exam")
        if label and label not in confirm_exam_eligible:
            confirm_exam_eligible.append(label)

    return {
        "evaluations": evaluations,
        "recommended_departments": departments,
        "confirm_exam_eligible": confirm_exam_eligible,
        "abnormal_count": sum(1 for e in evaluations if e["severity"] in ("high", "warning")),
        "high_risk_count": sum(1 for e in evaluations if e["severity"] == "high"),
    }
