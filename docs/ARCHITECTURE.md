# Architecture

## Design principles

1. **Deterministic first, LLM second.** Validation must be reproducible and
   runnable without any API key. The LLM only augments — it generates
   suggested questions, narrative summaries, and grounded chat answers.
2. **No hallucinations.** Chat replies cite numbered excerpts and declare a
   confidence level. The prompt explicitly instructs the model to say "not
   addressed" when the excerpts don't cover a question.
3. **Portable deployment.** Everything runs behind one `docker compose up`.
4. **Provider-agnostic LLM.** Switching between OpenAI, Anthropic, Groq, and
   Ollama is a single env var change.

## Backend structure

```
backend/app/
├── api/              # FastAPI routers (HTTP boundary)
│   ├── chat.py       # POST /chat/{id}, GET /chat/{id}/history
│   ├── reports.py    # Upload, list, get, questions, summary, delete
│   └── health.py
├── db/
│   ├── database.py   # Engine, session, Base, pgvector bootstrap
│   └── models.py     # Report, Chunk, ChatMessage ORM models
├── models/
│   └── schemas.py    # Pydantic request/response models
├── parsers/
│   └── pdf_parser.py # PyMuPDF + pdfplumber fallback
├── prompts/
│   └── templates.py  # Chat / questions / summary prompts
├── services/
│   ├── llm_service.py       # OpenAI|Anthropic|Groq|Ollama|Stub
│   ├── embedding_service.py # OpenAI embeddings + hash fallback + chunking
│   ├── retrieval_service.py # pgvector cosine search
│   ├── report_service.py    # Ingestion pipeline
│   ├── chat_service.py      # RAG chat with citation extraction
│   └── summary_service.py   # Questions + executive summary
├── validators/
│   └── soc2_validator.py    # Deterministic SOC 2 engine
└── utils/
    └── ratelimit.py         # SlowAPI limiter shared across routes
```

## Validation engine

[`soc2_validator.py`](../backend/app/validators/soc2_validator.py) is a pure
function: `(report_text) -> ValidationResult`. No DB, no LLM. It uses regex
patterns to detect:

- **Report type** — "Type I" vs "Type II" keywords; falls back to phrases like
  "for the period…through" (Type II) or "as of…" (Type I).
- **Opinion** — specifically looks for unqualified ("in our opinion…fairly
  presents"), qualified ("except for"), adverse, and disclaimer phrasing.
- **Dates** — supports long form ("January 15, 2024"), ISO, and slash notation.
  The coverage window uses a "for the period X through Y" sentence pattern.
- **Sections** — checks for independent auditor report, management assertion,
  system description, controls & tests, results/exceptions, CUECs, and
  subservice organizations via section-heading regex.
- **Trust Service Criteria** — keyword detection around the TSP framework.
- **Exceptions** — distinguishes "no exceptions noted" from "exceptions were
  identified".
- **Subservice orgs** — recognizes the top 10 common cloud providers.
- **Auditor firms** — matches a known list (Big Four, Schellman, A-LIGN, etc.)
  plus a generic "<Firm>, LLP" fallback.

Findings flow into a **risk score** (0-100): starts at 100, deducts 18 per
critical, 7 per warning, 1 per info. Maps to Strong / Moderate / Weak bands.

## RAG pipeline

**Chunking** happens per-page so we can attach page numbers to citations.
Chunks target 1500 chars with 200 char overlap, splitting on paragraph
boundaries when possible.

**Embeddings** default to OpenAI `text-embedding-3-small` (1536 dims). Without
a key, a hashing-based embedding is used so retrieval still works
deterministically — with reduced quality.

**Retrieval** uses pgvector's cosine distance operator `<=>` with an HNSW
index. We fetch `TOP_K=6` chunks, present them numbered to the LLM, and the
prompt requires inline `[n]` citations.

**Answer post-processing** in `chat_service.answer_question`:
1. Extract `Confidence: high|medium|low` and strip from visible text.
2. Parse inline `[n]` indices; map to retrieved chunks.
3. If no inline citations were produced, expose the top 2 retrieved chunks
   for transparency.
4. Persist user + assistant messages.

## Frontend structure

```
frontend/
├── app/
│   ├── layout.tsx               # Root layout with theme provider, header, footer
│   ├── page.tsx                 # Homepage: hero, upload, how-it-works, features, FAQ
│   ├── not-found.tsx
│   └── report/[id]/
│       ├── page.tsx             # Server component: fetch + render dashboard
│       └── loading.tsx
├── components/
│   ├── ui/                      # shadcn-style primitives
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── tabs.tsx
│   │   ├── badge.tsx
│   │   └── …
│   ├── site-header.tsx
│   ├── site-footer.tsx
│   ├── theme-provider.tsx
│   ├── theme-toggle.tsx
│   ├── upload-zone.tsx          # Drag-drop PDF upload with XHR progress
│   ├── report-dashboard.tsx     # 5 tabs + top summary cards
│   ├── overview-tab.tsx         # Identification, dates, criteria, sections
│   ├── validation-findings.tsx  # Findings grouped by severity
│   ├── suggested-questions.tsx  # Clickable question chips
│   ├── chat-interface.tsx       # ChatGPT-style chat with citations
│   └── summary-panel.tsx        # Executive summary + markdown export
├── lib/
│   ├── api.ts                   # Typed fetch client
│   └── utils.ts                 # cn(), formatters
└── types/
    └── index.ts                 # Shared TS types mirroring Pydantic
```

## Data flow for an upload

```
Browser            Frontend              Backend                 Postgres
│                     │                     │                         │
│ Pick PDF            │                     │                         │
│────────────────────▶│                     │                         │
│                     │ POST /api/upload    │                         │
│                     │────────────────────▶│                         │
│                     │                     │ parse_pdf (PyMuPDF)     │
│                     │                     │ SOC2Validator.validate()│
│                     │                     │ chunk + embed           │
│                     │                     │ INSERT reports, chunks  │
│                     │                     │────────────────────────▶│
│                     │                     │◀────────────────────────│
│                     │◀────────────────────│ UploadResponse          │
│◀────────────────────│ redirect /report/:id│                         │
│                     │ fetch /report/:id   │                         │
│                     │────────────────────▶│────────────────────────▶│
│                     │◀────────────────────│                         │
```

## Data flow for a chat question

```
Browser           Frontend          Backend                  Postgres    LLM
│                    │                │                          │         │
│ Ask question       │                │                          │         │
│───────────────────▶│                │                          │         │
│                    │ POST /chat/:id │                          │         │
│                    │───────────────▶│                          │         │
│                    │                │ embed(question)          │         │
│                    │                │ SELECT chunks ORDER BY   │         │
│                    │                │ embedding <=> q LIMIT 6  │         │
│                    │                │─────────────────────────▶│         │
│                    │                │◀─────────────────────────│         │
│                    │                │ complete(system, user)   │         │
│                    │                │─────────────────────────────────────▶│
│                    │                │◀─────────────────────────────────────│
│                    │                │ parse [n] + Confidence:  │         │
│                    │                │ INSERT chat_messages     │         │
│                    │                │─────────────────────────▶│         │
│                    │◀───────────────│                          │         │
│◀───────────────────│ render answer + citations                           │
```
