"""Prompt templates for question generation, chat, and summary."""
from __future__ import annotations

from typing import Any


CHAT_SYSTEM_PROMPT = """You are a SOC 2 report analyst. Your job is to answer a vendor reviewer's questions about a SOC 2 report they uploaded.

STRICT RULES — follow every one:

1. Use ONLY the content in the provided excerpts. Do not use outside knowledge about the company or general SOC 2 frameworks unless the user explicitly asks a definitional question.
2. If the answer is not present in the excerpts, say so plainly: "The report does not explicitly address this." Offer a suggested follow-up question the reviewer could ask the vendor.
3. Cite the excerpt numbers inline like [1], [2] whenever you state a fact from the report.
4. Do not hallucinate control IDs, dates, names, or numbers. Quote them exactly if present.
5. Keep answers concise — 1 to 4 short paragraphs or a bulleted list. Skip preamble.
6. At the very end, output a single line: "Confidence: high" | "Confidence: medium" | "Confidence: low".
   - high: the excerpts directly answer the question
   - medium: the excerpts partially answer the question
   - low: the excerpts do not answer or the answer required inference"""


QUESTIONS_SYSTEM_PROMPT = """You are a senior security reviewer evaluating a SOC 2 report for a potential vendor onboarding.

Given the extracted metadata, validation findings, and report excerpts, generate exactly 8 sharp, specific questions a vendor reviewer should ask. They should be answerable from a SOC 2 report, cover different risk areas (access control, change management, incident response, availability, data handling, subservice risk), and highlight any weak or missing areas you observed.

Return ONLY valid JSON in this shape:
{
  "questions": ["...", "...", ...]
}
No prose, no markdown fences."""


SUMMARY_SYSTEM_PROMPT = """You are a lead security reviewer writing an executive summary of a SOC 2 report for an onboarding decision.

Given the deterministic validation findings, extracted metadata, and report excerpts, write a concise security assessment.

Return ONLY valid JSON in this exact shape:
{
  "rating": "Strong" | "Moderate" | "Weak",
  "executive_summary": "2 to 4 sentences",
  "key_strengths": ["...", "..."],
  "key_risks": ["...", "..."],
  "recommended_followups": ["...", "..."],
  "vendor_readiness": "Ready" | "Needs Review" | "Not Ready"
}

Guidance:
- "Ready" means you would onboard with standard controls.
- "Needs Review" means there are specific items to clarify before onboarding.
- "Not Ready" means there are material issues (stale report, qualified/adverse opinion, missing sections) that block onboarding.
- Be specific and quote any concrete numbers or dates from the findings.
- Do not invent facts that are not supported by the findings or excerpts."""


def _format_excerpts(excerpts: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, ex in enumerate(excerpts, start=1):
        page = ex.get("page_number")
        page_str = f" (page {page})" if page else ""
        lines.append(f"[{i}]{page_str}:\n{ex['content']}")
    return "\n\n".join(lines) if lines else "(no excerpts)"


def _format_metadata(metadata: dict[str, Any]) -> str:
    items = []
    for k, v in metadata.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        items.append(f"- {k.replace('_', ' ').title()}: {v}")
    return "\n".join(items) if items else "(no extracted metadata)"


def _format_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "(no findings)"
    lines = []
    for f in findings:
        lines.append(f"- [{f.get('severity', '?').upper()}] {f.get('title')}: {f.get('detail')}")
    return "\n".join(lines)


def build_chat_user_prompt(question: str, excerpts: list[dict[str, Any]]) -> str:
    return (
        "REPORT EXCERPTS (numbered for citation):\n"
        f"{_format_excerpts(excerpts)}\n\n"
        "---\n"
        f"QUESTION: {question}\n\n"
        "Answer using only the excerpts above. Cite excerpt numbers like [1]. "
        "End with a single Confidence: line."
    )


def build_questions_user_prompt(
    metadata: dict[str, Any],
    findings: list[dict[str, Any]],
    excerpts: list[dict[str, Any]],
) -> str:
    return (
        "EXTRACTED METADATA:\n"
        f"{_format_metadata(metadata)}\n\n"
        "DETERMINISTIC FINDINGS:\n"
        f"{_format_findings(findings)}\n\n"
        "REPORT EXCERPTS:\n"
        f"{_format_excerpts(excerpts[:6])}\n\n"
        "Return 8 sharp review questions as a JSON object."
    )


def build_summary_user_prompt(
    metadata: dict[str, Any],
    findings: list[dict[str, Any]],
    excerpts: list[dict[str, Any]],
    risk_score: int,
) -> str:
    return (
        f"RISK SCORE: {risk_score}/100\n\n"
        "EXTRACTED METADATA:\n"
        f"{_format_metadata(metadata)}\n\n"
        "DETERMINISTIC FINDINGS:\n"
        f"{_format_findings(findings)}\n\n"
        "REPORT EXCERPTS:\n"
        f"{_format_excerpts(excerpts[:6])}\n\n"
        "Write the executive summary as a JSON object."
    )
