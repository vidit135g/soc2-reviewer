"""PDF text extraction using PyMuPDF (primary) with pdfplumber fallback.

The parser now returns a *structured* result the extraction pipeline can use:

- per-page text, normalised whitespace, page boundaries preserved
- per-page "blocks" with font-size/bold hints (when available) so the
  company-name extractor can rank candidates by visual prominence
- per-page tables (pdfplumber) — useful for CUEC tables, control tables
- PDF metadata (title, author) from the file info dict

The result is still JSON-safe (dataclasses with primitive types) so it
can be pickled for the two-phase ingestion pipeline.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
    """A contiguous visual block of text on a page.

    `size` is the largest font size within the block (in pt); `bold` is
    True if any run in the block is bold. These are used by the
    company-name extractor to score candidates by visual prominence
    (cover-page titles are big-font and/or bold).
    """

    text: str
    size: float = 0.0
    bold: bool = False
    y_top: float = 0.0  # vertical position (lower = higher on the page)


@dataclass
class PDFPage:
    number: int  # 1-indexed
    text: str
    blocks: list[TextBlock] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class PDFParseResult:
    page_count: int
    pages: list[PDFPage]
    full_text: str
    title: str | None = None
    author: str | None = None
    used_fallback: bool = False
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_WS_RUN = re.compile(r"[ \t]+")
_TRIPLE_NL = re.compile(r"\n{3,}")


def _normalise(text: str) -> str:
    """Collapse whitespace runs but preserve paragraph boundaries."""
    if not text:
        return ""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    out = _WS_RUN.sub(" ", out)
    # Strip trailing spaces before newlines
    out = re.sub(r" +\n", "\n", out)
    out = _TRIPLE_NL.sub("\n\n", out)
    return out.strip()


# ---------------------------------------------------------------------------
# PyMuPDF path
# ---------------------------------------------------------------------------


def _blocks_from_pymupdf_page(page: "fitz.Page") -> list[TextBlock]:
    """Extract visual text blocks with font-size + bold metadata.

    We walk the 'dict' representation — each block contains lines, each
    line contains spans with their own font + size. We aggregate spans
    line-by-line so a heading like "ACME CORPORATION" remains a single
    high-score candidate instead of 18 one-char spans.
    """
    blocks: list[TextBlock] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return blocks

    for b in data.get("blocks", []):
        if b.get("type", 0) != 0:  # 0 = text; 1 = image
            continue
        y_top = float(b.get("bbox", [0, 0, 0, 0])[1] or 0.0)
        for line in b.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text_parts: list[str] = []
            max_size = 0.0
            any_bold = False
            for span in spans:
                s_text = span.get("text", "") or ""
                if not s_text.strip():
                    continue
                text_parts.append(s_text)
                size = float(span.get("size", 0) or 0)
                if size > max_size:
                    max_size = size
                flags = int(span.get("flags", 0) or 0)
                # Flag bit 4 (16) = bold in PyMuPDF
                if flags & 16 or "bold" in str(span.get("font", "")).lower():
                    any_bold = True
            line_text = " ".join(text_parts).strip()
            if line_text:
                blocks.append(
                    TextBlock(
                        text=line_text,
                        size=max_size,
                        bold=any_bold,
                        y_top=y_top,
                    )
                )
    return blocks


def _extract_with_pymupdf(path: Path) -> PDFParseResult:
    pages: list[PDFPage] = []
    title: str | None = None
    author: str | None = None
    with fitz.open(path) as doc:
        meta = doc.metadata or {}
        raw_title = (meta.get("title") or "").strip() or None
        raw_author = (meta.get("author") or "").strip() or None
        title = raw_title if raw_title else None
        author = raw_author if raw_author else None

        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            blocks = _blocks_from_pymupdf_page(page)
            pages.append(
                PDFPage(
                    number=i,
                    text=_normalise(text),
                    blocks=blocks,
                )
            )
    full_text = "\n\n".join(f"[page {p.number}]\n{p.text}" for p in pages if p.text)
    return PDFParseResult(
        page_count=len(pages),
        pages=pages,
        full_text=full_text,
        title=title,
        author=author,
    )


# ---------------------------------------------------------------------------
# pdfplumber path — used as text fallback AND always for tables on the first
# 150 pages (CUECs usually live there). Tables on later pages are skipped
# to bound worst-case parse time on 500-page appendix-heavy reports.
# ---------------------------------------------------------------------------

_TABLE_PAGE_CAP = 150


def _extract_tables_with_pdfplumber(path: Path) -> dict[int, list[list[list[str]]]]:
    """Best-effort table extraction. Key = 1-indexed page number."""
    tables: dict[int, list[list[list[str]]]] = {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages[:_TABLE_PAGE_CAP], start=1):
                try:
                    page_tables = page.extract_tables() or []
                except Exception as exc:
                    logger.debug("pdfplumber table extract failed on p.%d: %s", i, exc)
                    continue
                cleaned: list[list[list[str]]] = []
                for t in page_tables:
                    rows = [
                        [((cell or "").strip()) for cell in row]
                        for row in t
                        if any((cell or "").strip() for cell in row)
                    ]
                    if rows:
                        cleaned.append(rows)
                if cleaned:
                    tables[i] = cleaned
    except Exception as exc:
        logger.warning("pdfplumber table pass failed: %s", exc)
    return tables


def _extract_with_pdfplumber(path: Path) -> PDFParseResult:
    pages: list[PDFPage] = []
    warnings: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover — defensive
                warnings.append(f"page {i} extraction failed: {exc}")
                text = ""
            pages.append(PDFPage(number=i, text=_normalise(text)))
    full_text = "\n\n".join(f"[page {p.number}]\n{p.text}" for p in pages if p.text)
    return PDFParseResult(
        page_count=len(pages),
        pages=pages,
        full_text=full_text,
        used_fallback=True,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf(path: str | Path, *, extract_tables: bool = True) -> PDFParseResult:
    """Extract text + structure from a PDF.

    Strategy:
    1. PyMuPDF for text + block font metadata (fast, accurate).
    2. pdfplumber fallback if PyMuPDF yields near-empty text.
    3. pdfplumber table pass (first 150 pages) unless disabled.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")

    try:
        result = _extract_with_pymupdf(p)
    except Exception as exc:
        logger.warning("PyMuPDF extraction failed (%s); falling back to pdfplumber", exc)
        result = _extract_with_pdfplumber(p)
    else:
        # If we got hardly any text, try pdfplumber
        if len(result.full_text.strip()) < 500 and result.page_count > 0:
            logger.info("PyMuPDF produced sparse text; retrying with pdfplumber")
            try:
                fallback = _extract_with_pdfplumber(p)
                if len(fallback.full_text.strip()) > len(result.full_text.strip()):
                    # Preserve title/author from PyMuPDF metadata if pdfplumber lacked them
                    fallback.title = fallback.title or result.title
                    fallback.author = fallback.author or result.author
                    result = fallback
            except Exception as exc:  # pragma: no cover
                logger.warning("pdfplumber fallback failed: %s", exc)

    if extract_tables:
        try:
            tables_by_page = _extract_tables_with_pdfplumber(p)
            for page in result.pages:
                page.tables = tables_by_page.get(page.number, [])
        except Exception as exc:
            logger.warning("Table extraction pass failed: %s", exc)

    return result
