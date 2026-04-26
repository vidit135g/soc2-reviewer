"""Weighted 5-category scoring for SOC 2 reports.

Replaces the previous "deduct N points per severity" heuristic with a
transparent 100-point model made of five categories:

| Category                | Weight | What it measures                                     |
|-------------------------|--------|------------------------------------------------------|
| Metadata Completeness   | 25     | Did we extract company, auditor, dates, scope?       |
| Coverage Quality        | 20     | Is the audit window a meaningful duration?           |
| Control Transparency    | 20     | CUECs, subservices, criteria all documented?         |
| Opinion Strength        | 20     | Unqualified > qualified > adverse/disclaimer/missing |
| Structure Quality       | 15     | Required sections present?                           |

Each category yields 0.0–1.0 which multiplies its weight. The final
score is the sum — out of 100, higher is better. An ``adverse`` or
``disclaimer`` opinion forces a ``Weak`` rating regardless of score.

Outputs:

- ``total`` — 0..100 integer
- ``rating`` — Strong / Moderate / Weak / Unknown
- ``category_scores`` — the 5 sub-scores for the UI
- ``reasons`` — human-readable lines explaining each deduction
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .types import Confidence, ExtractionBundle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-category scorers — each returns (score_0_to_1, reason_lines).
# ---------------------------------------------------------------------------


def _score_metadata_completeness(
    bundle: ExtractionBundle,
) -> tuple[float, list[str]]:
    fields = [
        "company_name",
        "auditor_firm",
        "report_type",
        "opinion",
        "opinion_date",
        "coverage_start",
        "coverage_end",
    ]
    weight_total = len(fields)
    got = 0.0
    reasons: list[str] = []
    for f in fields:
        fe = bundle.get(f)
        if not fe.is_present:
            reasons.append(f"Missing {f.replace('_', ' ')}")
            continue
        # Confidence downweights: HIGH=1.0, MEDIUM=0.85, LOW=0.6
        if fe.confidence is Confidence.HIGH:
            got += 1.0
        elif fe.confidence is Confidence.MEDIUM:
            got += 0.85
        elif fe.confidence is Confidence.LOW:
            got += 0.6
            reasons.append(f"Low-confidence {f.replace('_', ' ')}")
        else:
            reasons.append(f"Missing {f.replace('_', ' ')}")
    return got / weight_total, reasons


def _score_coverage_quality(
    bundle: ExtractionBundle,
) -> tuple[float, list[str]]:
    start: date | None = bundle.get("coverage_start").value
    end: date | None = bundle.get("coverage_end").value
    report_type = bundle.get("report_type").value

    if report_type == "SOC 2 Type I":
        # Type I is point-in-time — coverage quality is N/A; award full marks
        # if the "as of" date was captured, else 0.5 for the missing-but-ok case.
        if start and end and start == end:
            return 1.0, []
        if start:
            return 0.9, []
        return 0.5, ["Type I report: coverage date not captured"]

    if not (start and end):
        return 0.0, ["Coverage period missing"]
    days = (end - start).days
    if days <= 0:
        return 0.0, ["Coverage window is invalid"]
    if days >= 365:
        return 1.0, []
    if days >= 270:
        return 0.9, ["Coverage window under 12 months"]
    if days >= 180:
        return 0.75, [f"Short coverage window ({days} days)"]
    if days >= 90:
        return 0.5, [f"Very short coverage window ({days} days)"]
    return 0.2, [f"Coverage window is only {days} days"]


def _score_control_transparency(
    bundle: ExtractionBundle,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    sub_total = 0.0
    weight = 0.0

    # (a) CUECs — 0.4 weight
    weight += 0.4
    cuecs = bundle.get("complementary_user_entity_controls")
    if cuecs.is_present and isinstance(cuecs.value, list) and len(cuecs.value) >= 3:
        sub_total += 0.4
    elif cuecs.is_present:
        sub_total += 0.25
        reasons.append("Few CUECs captured")
    else:
        reasons.append("No CUECs identified")

    # (b) Trust criteria — 0.3 weight
    weight += 0.3
    crit = bundle.get("trust_service_criteria").value or []
    if crit:
        # Reward breadth: 1 criterion = 0.6, 2 = 0.8, 3+ = 1.0
        factor = {1: 0.6, 2: 0.8}.get(len(crit), 1.0)
        sub_total += 0.3 * factor
        if len(crit) == 1:
            reasons.append("Only one Trust Service Criterion in scope")
    else:
        reasons.append("Trust Service Criteria not detected")

    # (c) Subservice orgs — 0.2 weight (subservices are common; we reward
    # their explicit disclosure, not their presence)
    weight += 0.2
    subs = bundle.get("subservice_organizations")
    if subs.is_present:
        sub_total += 0.2
    elif subs.confidence is Confidence.LOW:
        sub_total += 0.12
        reasons.append("Subservice orgs referenced but not identified")
    else:
        sub_total += 0.1  # not a red flag — many reports have none
        reasons.append("No subservice organizations disclosed")

    # (d) Exceptions summary — 0.1 weight (presence, not polarity; polarity
    # is punished via findings but here we just want to know the topic was
    # addressed)
    weight += 0.1
    ex = bundle.get("exceptions_summary")
    if ex.is_present and ex.confidence is not Confidence.LOW:
        sub_total += 0.1
    else:
        sub_total += 0.05
        reasons.append("Exceptions not explicitly addressed")

    return sub_total / weight if weight else 0.0, reasons


def _score_opinion_strength(
    bundle: ExtractionBundle,
) -> tuple[float, list[str]]:
    op_fe = bundle.get("opinion")
    op = op_fe.value
    if op == "unqualified":
        return 1.0, []
    if op == "qualified":
        return 0.6, ["Qualified opinion"]
    if op == "adverse":
        return 0.0, ["Adverse opinion"]
    if op == "disclaimer":
        return 0.0, ["Disclaimer of opinion"]
    return 0.4, ["Opinion not classified"]


def _score_structure_quality(
    bundle: ExtractionBundle,
) -> tuple[float, list[str]]:
    missing = bundle.get("sections_missing").value or []
    present = bundle.get("sections_present").value or []

    if not present and not missing:
        return 0.5, ["Section detection did not run"]

    # Weight the four critical sections more heavily
    critical = {
        "independent_auditor_report",
        "management_assertion",
        "system_description",
        "controls_and_tests",
    }
    crit_total = len(critical)
    crit_have = sum(1 for k in critical if k not in missing)
    crit_ratio = crit_have / crit_total if crit_total else 1.0

    other = {
        "results_and_exceptions",
        "complementary_user_entity_controls",
        "subservice_organizations",
    }
    other_total = len(other)
    other_have = sum(1 for k in other if k not in missing)
    other_ratio = other_have / other_total if other_total else 1.0

    # 70% critical, 30% other
    ratio = 0.7 * crit_ratio + 0.3 * other_ratio

    reasons: list[str] = []
    for m in missing:
        if m in critical:
            reasons.append(f"Missing critical section: {m.replace('_', ' ')}")
        else:
            reasons.append(f"Missing section: {m.replace('_', ' ')}")
    return ratio, reasons


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


@dataclass
class ScoringResult:
    total: int
    rating: str
    category_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


# Weights sum to 100.
_WEIGHTS: dict[str, int] = {
    "metadata_completeness": 25,
    "coverage_quality": 20,
    "control_transparency": 20,
    "opinion_strength": 20,
    "structure_quality": 15,
}


_SCORERS = {
    "metadata_completeness": _score_metadata_completeness,
    "coverage_quality": _score_coverage_quality,
    "control_transparency": _score_control_transparency,
    "opinion_strength": _score_opinion_strength,
    "structure_quality": _score_structure_quality,
}


def score_report(bundle: ExtractionBundle) -> ScoringResult:
    total = 0.0
    reasons: list[str] = []
    category_scores: dict[str, dict[str, Any]] = {}

    for name, scorer in _SCORERS.items():
        ratio, cat_reasons = scorer(bundle)
        weight = _WEIGHTS[name]
        points = ratio * weight
        total += points
        category_scores[name] = {
            "ratio": round(ratio, 3),
            "weight": weight,
            "points": round(points, 2),
            "reasons": cat_reasons,
        }
        reasons.extend(cat_reasons)

    total_int = max(0, min(100, int(round(total))))

    # Opinion override — adverse / disclaimer force Weak regardless of score.
    op = bundle.get("opinion").value
    if op in {"adverse", "disclaimer"}:
        rating = "Weak"
    elif total_int >= 80:
        rating = "Strong"
    elif total_int >= 55:
        rating = "Moderate"
    elif total_int > 0:
        rating = "Weak"
    else:
        rating = "Unknown"

    logger.info(
        "[EVALUATE] score=%d rating=%s categories=%s",
        total_int, rating,
        {k: v["points"] for k, v in category_scores.items()},
    )

    return ScoringResult(
        total=total_int,
        rating=rating,
        category_scores=category_scores,
        reasons=reasons,
    )
