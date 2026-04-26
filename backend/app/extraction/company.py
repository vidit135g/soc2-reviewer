"""Company-name extraction.

The *service organisation* (the audited company) is usually the single most
visually prominent entity on the cover page of a SOC 2 report. Previous
heuristics leaned on a single regex over the first few thousand characters
and routinely picked up the auditor firm, a subsidiary mentioned in the
header, or an incidental "Management of X" sentence.

This module uses three complementary signals, then fuses them:

1. **Font prominence** (cover page). PyMuPDF gives us ``TextBlock`` metadata
   with font size + bold flag; the largest, bold, top-of-page line with an
   entity suffix is almost always the service-organisation name.
2. **Heading cue**. Phrases like *"Description of [Company]'s System"*,
   *"Management of [Company]"*, *"[Company], the Service Organization"* lock
   onto the entity unambiguously when present.
3. **PDF /Info metadata**. The PDF's own title field often already contains
   the company name — useful as a tie-breaker.

Known auditor firms (Deloitte, KPMG, A-LIGN, Schellman, BDO, etc.) are
hard-excluded so we never return the audit firm as the company.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from app.parsers.pdf_parser import PDFPage, PDFParseResult, TextBlock

from .text_utils import ENTITY_SUFFIX_PATTERN, collapse_whitespace, excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)

# Auditor firms we explicitly never treat as the audited company.
# Lower-cased, substring-matched.
AUDITOR_EXCLUSIONS = {
    "deloitte", "ernst & young", " ey ", "kpmg",
    "pricewaterhousecoopers", "pwc", "bdo", "grant thornton",
    "rsm", "crowe", "a-lign", "a lign", "schellman",
    "prescient assurance", "coalfire", "insight assurance",
    "moss adams", "bpm", "johanson", "sensiba", "truvantis",
    "360 advanced", "tugboat logic", "armanino",
}

# Cover-page words that should NEVER be the entire company name.
GENERIC_BLACKLIST = {
    "soc 2", "soc 2 report", "soc 2 type i report", "soc 2 type ii report",
    "system and organization controls", "report on controls",
    "service organization controls report",
    "independent service auditor's report",
    "independent auditor's report",
    "type ii report", "type i report",
    "examination report", "attestation report",
    "confidential", "draft", "table of contents",
    "management's assertion", "assertion of management",
    "description of the system", "system description",
}

# Strict: the matched string must END with an entity suffix (or contain one)
# and the head must look like a proper noun.
_SUFFIX_RE = re.compile(rf"\b{ENTITY_SUFFIX_PATTERN}\b", re.IGNORECASE)

# Proper-noun head: words starting with caps, optionally with & and .
# Allows hyphenation ("WP-LLC-style") and ampersands ("Procter & Gamble").
_NAME_HEAD = r"[A-Z][A-Za-z0-9&@.'\-]*(?:\s+(?:and\s+|&\s+|de\s+|of\s+)?[A-Z][A-Za-z0-9&@.'\-]*){0,6}"

# "X, Inc." / "X Inc" / "X LLC" / "X Holdings Inc."
_FULL_NAME_RE = re.compile(
    rf"({_NAME_HEAD})(?:,?\s+)?({ENTITY_SUFFIX_PATTERN}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)",
)


@dataclass
class _Candidate:
    name: str
    score: float
    method: str
    evidence: str
    page_number: int | None = None


# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------


def _clean(name: str) -> str:
    name = collapse_whitespace(name)
    # Trim surrounding whitespace / commas / colons / dashes. We deliberately
    # KEEP a trailing period so "Inc." stays "Inc." — stripping the dot
    # mangled names like "ACME Widgets, Inc." into "ACME Widgets, Inc".
    name = name.strip(",;: -")
    # Compress duplicate spaces
    name = re.sub(r"\s+", " ", name)
    # Drop trailing possessive "'s"
    name = re.sub(r"'s$", "", name)
    # Drop a trailing single quote left from matching "X'"
    name = name.rstrip("'")
    return name


def _looks_like_auditor(name: str) -> bool:
    n = f" {name.lower()} "
    return any(auditor in n for auditor in AUDITOR_EXCLUSIONS)


def _looks_generic(name: str) -> bool:
    low = name.lower().strip()
    if low in GENERIC_BLACKLIST:
        return True
    # Near-matches
    if any(kw in low for kw in {"soc 2", "soc2", "system and organization", "assertion"}):
        return True
    return False


def _has_entity_suffix(name: str) -> bool:
    return bool(_SUFFIX_RE.search(name))


def _candidate_valid(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 120:
        return False
    if _looks_generic(name):
        return False
    if _looks_like_auditor(name):
        return False
    # Reject if it's all caps AND has no vowels (likely a code, not a name)
    if name.isupper() and not re.search(r"[AEIOU]", name):
        return False
    return True


# ---------------------------------------------------------------------------
# Layer 1 — cover-page font prominence
# ---------------------------------------------------------------------------


def _prominent_lines(pages: list[PDFPage], max_pages: int = 3) -> list[tuple[TextBlock, int]]:
    """Return ``(block, page_num)`` for all top blocks on the first few
    pages, sorted by font size descending then by vertical position.
    """
    collected: list[tuple[TextBlock, int]] = []
    for p in pages[:max_pages]:
        if not p.blocks:
            continue
        # Sort: biggest font first, then highest on the page
        blocks = sorted(p.blocks, key=lambda b: (-b.size, b.y_top))
        # Take the top-12 so we have enough to score
        for b in blocks[:12]:
            collected.append((b, p.number))
    return collected


def _score_font_candidate(text: str, block: TextBlock, max_size: float) -> float:
    """Score a cover-page block as a company-name candidate."""
    score = 0.0
    # Font size relative to the largest on cover
    if max_size > 0:
        score += (block.size / max_size) * 10.0
    if block.bold:
        score += 2.0
    # Presence of a legal-entity suffix is a big signal
    if _has_entity_suffix(text):
        score += 6.0
    # Short-ish "company-like" length (2–8 words typical)
    words = text.split()
    if 2 <= len(words) <= 8:
        score += 2.0
    # Upper / title case bias
    if text[0].isupper():
        score += 0.5
    # Penalise all-caps boilerplate
    if text.isupper() and len(words) > 6:
        score -= 2.0
    # Penalise if it contains forbidden phrases
    if _looks_generic(text) or _looks_like_auditor(text):
        score -= 50.0
    return score


def _extract_name_from_block_text(text: str) -> str | None:
    """Pull a proper-noun + suffix company name out of a line of text."""
    text = collapse_whitespace(text)
    m = _FULL_NAME_RE.search(text)
    if m:
        cleaned = _clean(m.group(0))
        if _candidate_valid(cleaned):
            return cleaned
    # Fallback: if the whole line ends with an entity suffix, use the whole
    # line
    if _SUFFIX_RE.search(text):
        cleaned = _clean(text)
        if _candidate_valid(cleaned):
            return cleaned
    return None


def _cover_page_candidates(pages: list[PDFPage]) -> list[_Candidate]:
    """Cover-page font-prominence candidates."""
    entries = _prominent_lines(pages)
    if not entries:
        return []
    max_size = max(b.size for b, _ in entries) or 1.0
    out: list[_Candidate] = []
    for block, page_num in entries:
        text = block.text
        name = _extract_name_from_block_text(text)
        if not name:
            continue
        score = _score_font_candidate(name, block, max_size)
        if score <= 0:
            continue
        out.append(
            _Candidate(
                name=name,
                score=score,
                method="rule_font",
                evidence=collapse_whitespace(text)[:280],
                page_number=page_num,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Layer 2 — heading cues ("Management of X", "Description of X's System")
# ---------------------------------------------------------------------------

# Each pattern captures the company name in group 1. Ordered from most to
# least specific. We only search the first ~40k chars so we don't catch
# "Management of the AWS Environment" 200 pages in.
_HEADING_CUES: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(
            rf"Description of ({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)['’]s?\s+System",
        ),
        "description_of_system",
        9.0,
    ),
    (
        re.compile(
            rf"({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)['’]s\s+(?:System|Service Organization)",
        ),
        "possessive_system",
        8.0,
    ),
    (
        re.compile(
            rf"Management of ({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)",
        ),
        "management_of",
        7.5,
    ),
    (
        re.compile(
            rf"({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)\s*,?\s*(?:the\s+)?Service Organization",
            re.IGNORECASE,
        ),
        "named_service_org",
        8.0,
    ),
    (
        re.compile(
            rf"(?:the\s+)?Service Organization\s*,?\s*({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)",
            re.IGNORECASE,
        ),
        "service_org_colon",
        7.0,
    ),
    (
        re.compile(
            rf"({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)\s+\(the\s+[\"'\u201c\u201d]?Company[\"'\u201c\u201d]?\)",
            re.IGNORECASE,
        ),
        "the_company_paren",
        8.5,
    ),
    (
        re.compile(
            rf"prepared by ({_NAME_HEAD}(?:,?\s+{ENTITY_SUFFIX_PATTERN})?)",
            re.IGNORECASE,
        ),
        "prepared_by",
        6.0,
    ),
]


def _heading_candidates(full_text: str, window: int = 60_000) -> list[_Candidate]:
    head = full_text[:window]
    out: list[_Candidate] = []
    counted: dict[str, float] = {}
    for pattern, method, base_score in _HEADING_CUES:
        for m in pattern.finditer(head):
            name = _clean(m.group(1))
            if not _candidate_valid(name):
                continue
            # Multiple hits for the same name → compound score
            counted[name] = counted.get(name, 0.0) + base_score
            # Stash evidence only for the first hit per name
            if not any(c.name == name for c in out):
                out.append(
                    _Candidate(
                        name=name,
                        score=base_score,
                        method=f"rule_heading:{method}",
                        evidence=excerpt_around(head, m.start(), m.end(), padding=80),
                    )
                )
    # Merge compound scores back
    for c in out:
        c.score = counted.get(c.name, c.score)
    return out


# ---------------------------------------------------------------------------
# Layer 3 — PDF /Info metadata
# ---------------------------------------------------------------------------


def _metadata_candidate(title: str | None) -> _Candidate | None:
    if not title:
        return None
    title = collapse_whitespace(title)
    # Try to pull an entity from the title string
    name = _extract_name_from_block_text(title) or (title if _candidate_valid(title) else None)
    if not name:
        return None
    return _Candidate(
        name=name,
        score=3.0,  # metadata alone is a weak signal
        method="rule_metadata",
        evidence=f"PDF /Info title: {title}",
    )


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def _fuse(candidates: Iterable[_Candidate]) -> list[_Candidate]:
    """Collapse candidates that refer to the same entity (case-insensitive,
    ignoring trailing punctuation), summing scores."""
    by_key: dict[str, _Candidate] = {}
    for c in candidates:
        key = re.sub(r"[^a-z0-9]", "", c.name.lower())
        if not key:
            continue
        if key in by_key:
            existing = by_key[key]
            existing.score += c.score
            # Prefer evidence from the higher-confidence method
            if c.method.startswith("rule_heading") and not existing.method.startswith("rule_heading"):
                existing.method = c.method
                existing.evidence = c.evidence
                existing.page_number = c.page_number
        else:
            by_key[key] = _Candidate(**c.__dict__)
    return sorted(by_key.values(), key=lambda x: -x.score)


def _confidence_for_score(top: _Candidate, runner_up: float) -> Confidence:
    """Map the top score + margin to a Confidence level."""
    margin = top.score - runner_up
    if top.score >= 14.0 and margin >= 3.0:
        return Confidence.HIGH
    if top.score >= 9.0:
        return Confidence.MEDIUM
    if top.score > 0:
        return Confidence.LOW
    return Confidence.NONE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_company_name(parsed: PDFParseResult) -> FieldExtraction[str]:
    candidates: list[_Candidate] = []
    candidates.extend(_cover_page_candidates(parsed.pages))
    candidates.extend(_heading_candidates(parsed.full_text))
    meta_cand = _metadata_candidate(parsed.title)
    if meta_cand:
        candidates.append(meta_cand)

    if not candidates:
        return FieldExtraction(value=None, confidence=Confidence.NONE, method="missing")

    fused = _fuse(candidates)
    top = fused[0]
    runner_up_score = fused[1].score if len(fused) > 1 else 0.0
    conf = _confidence_for_score(top, runner_up_score)

    # Normalise the internal candidate method string (which may carry a
    # sub-variant like "rule_heading:management_of") to one of the canonical
    # ExtractionMethod literals. The sub-variant stays in evidence.
    raw_method = top.method
    if raw_method.startswith("rule_heading"):
        canonical_method = "rule_heading"
    elif raw_method in {"rule_font", "rule_metadata", "rule_composite", "rule_regex"}:
        canonical_method = raw_method
    else:
        canonical_method = "rule_composite"

    logger.debug(
        "[EXTRACT][company] top=%r score=%.2f runner_up=%.2f conf=%s method=%s",
        top.name, top.score, runner_up_score, conf.value, canonical_method,
    )
    return FieldExtraction(
        value=top.name,
        confidence=conf,
        method=canonical_method,
        evidence=top.evidence,
        page_number=top.page_number,
        alternatives=[(c.name, c.score) for c in fused[1:6]],
    )
