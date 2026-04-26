import Link from "next/link";
import { ArrowRight, Upload } from "lucide-react";

import { UploadZone } from "@/components/upload-zone";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <>
      {/* HERO — background is the page-wide AnimatedBackdrop mounted in    */}
      {/* app/layout.tsx. We don't duplicate the mesh here.                  */}
      <section className="relative">
        <div className="container relative pt-16 pb-12 md:pt-24 md:pb-20">
          <div className="mx-auto max-w-4xl text-center">
            <div className="font-mono text-[12px] uppercase tracking-[0.18em] text-black/60 dark:text-white/60">
              Vendor security &middot; AI-assisted
            </div>
            <h1 className="mt-6 font-serif text-6xl leading-[0.95] tracking-tight text-ink dark:text-paper md:text-7xl">
              Review a SOC 2 report in under a minute.
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-black/60 dark:text-white/60 md:text-xl">
              Upload a SOC 2 report and instantly validate, analyze, and ask
              security questions — grounded only in the report.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Button variant="pill" size="pill" asChild>
                <Link href="#upload">
                  <Upload className="mr-2 h-3.5 w-3.5" />
                  Upload report
                </Link>
              </Button>
              <Button variant="pill-outline" size="pill" asChild>
                <Link href="#how-it-works">
                  See how it works
                  <ArrowRight className="ml-2 h-3.5 w-3.5" />
                </Link>
              </Button>
            </div>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 font-mono text-[11px] uppercase tracking-[0.18em] text-black/45 dark:text-white/45">
              <span>Deterministic validation</span>
              <span className="hidden md:inline">&middot;</span>
              <span>No hallucinations</span>
              <span className="hidden md:inline">&middot;</span>
              <span>Choose any LLM</span>
            </div>
          </div>

          <div className="mx-auto mt-16 max-w-3xl">
            <UploadZone />
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how-it-works" className="container py-24">
        <SectionHeader
          eyebrow="How it works"
          title="From upload to decision in under a minute."
          description="Every report passes the same pipeline: deterministic validation first, grounded AI analysis second."
        />
        <div className="mt-14 grid gap-5 md:grid-cols-4">
          <Step
            step="01"
            title="Upload PDF"
            description="Drop any SOC 2 Type I or Type II report. We accept PDFs up to 50MB."
          />
          <Step
            step="02"
            title="Parse & extract"
            description="PyMuPDF extracts the full text. We identify company, auditor, dates, criteria, and sections."
          />
          <Step
            step="03"
            title="Validate"
            description="Heuristic engine flags missing sections, stale reports, qualified opinions, and scope issues."
          />
          <Step
            step="04"
            title="Analyze & ask"
            description="Generate a summary, review questions, and chat with answers grounded in exact excerpts."
          />
        </div>
      </section>

      {/* FEATURES */}
      <section id="features" className="container py-24">
        <SectionHeader
          eyebrow="Features"
          title="Everything a vendor reviewer needs."
        />
        <div className="mt-14 grid gap-5 md:grid-cols-3">
          <FeatureCard
            title="Structured validation"
            bullets={[
              "Type I vs Type II detection",
              "Opinion classification",
              "Coverage window analysis",
              "Missing section flags",
              "Stale report warnings",
            ]}
          />
          <FeatureCard
            title="Metadata extraction"
            bullets={[
              "Company & auditor firm",
              "Opinion date & coverage period",
              "Trust Service Criteria",
              "Subservice organizations",
              "CUECs referenced",
            ]}
          />
          <FeatureCard
            title="Grounded chat"
            bullets={[
              "Inline citations to excerpts",
              "Confidence label on each answer",
              "Declines to fabricate when silent",
              "Suggested review questions",
              "Full chat history retained",
            ]}
          />
          <FeatureCard
            title="Executive summary"
            bullets={[
              "Strong / Moderate / Weak rating",
              "Key strengths and risks",
              "Vendor readiness call",
              "Recommended follow-ups",
              "Exportable markdown",
            ]}
          />
          <FeatureCard
            title="Pluggable LLM"
            bullets={[
              "OpenAI",
              "Anthropic",
              "Groq",
              "Ollama (local)",
              "Deterministic stub fallback",
            ]}
          />
          <FeatureCard
            title="Enterprise-friendly"
            bullets={[
              "Dockerized deployment",
              "Rate limiting",
              "CORS controls",
              "PDF-only uploads",
              "Deletable at any time",
            ]}
          />
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="container py-24">
        <SectionHeader eyebrow="FAQ" title="Common questions." />
        <div className="mt-14 grid gap-4 md:grid-cols-2">
          <FAQ
            q="Does this replace a security reviewer?"
            a="No. It accelerates the review — structured validation catches mechanical issues (stale date, missing sections, qualified opinions) and the chat lets you ask specific questions. Final judgment stays with the reviewer."
          />
          <FAQ
            q="How do you prevent hallucinations?"
            a="Chat answers use retrieval-augmented generation with inline citations. If the report doesn't address a question, the assistant says so and suggests a follow-up to ask the vendor."
          />
          <FAQ
            q="Can I use a different LLM?"
            a="Yes. Set LLM_PROVIDER to openai, anthropic, groq, or ollama (local). No provider required for validation — only chat and summary need one."
          />
          <FAQ
            q="What happens to my reports?"
            a="Parsed text, embeddings, and chat history are stored in your Postgres. Delete a report to purge everything associated. Uploaded PDFs are removed from disk immediately after parsing."
          />
        </div>
      </section>

      {/* FINAL CTA — signature offset card */}
      <section className="container pb-24 pt-8">
        <div className="dia-offset-card mx-auto max-w-4xl p-10 text-center md:p-14">
          <div className="font-mono text-[12px] uppercase tracking-[0.18em] text-black/60 dark:text-white/60">
            Get started
          </div>
          <h3 className="mt-4 font-serif text-4xl leading-[1.05] tracking-tight text-ink dark:text-paper md:text-5xl">
            Ready to review your next vendor?
          </h3>
          <p className="mx-auto mt-4 max-w-lg text-base text-black/60 dark:text-white/60">
            Drop a PDF above. A full assessment is ready in under a minute.
          </p>
          <Button className="mt-8" variant="pill" size="pill" asChild>
            <Link href="#upload">
              <Upload className="mr-2 h-3.5 w-3.5" />
              Upload a SOC 2 report
            </Link>
          </Button>
        </div>
      </section>
    </>
  );
}

// -------- helpers ---------

function SectionHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <div className="mx-auto max-w-3xl text-center">
      <div className="font-mono text-[12px] uppercase tracking-[0.18em] text-black/60 dark:text-white/60">
        {eyebrow}
      </div>
      <h2 className="mt-4 font-serif text-4xl leading-[1.05] tracking-tight text-ink dark:text-paper md:text-5xl">
        {title}
      </h2>
      {description && (
        <p className="mx-auto mt-4 max-w-xl text-base text-black/60 dark:text-white/60 md:text-lg">
          {description}
        </p>
      )}
    </div>
  );
}

function Step({
  step,
  title,
  description,
}: {
  step: string;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-black/10 bg-white p-6 shadow-skill transition-all duration-200 ease-[cubic-bezier(0.215,0.61,0.355,1)] hover:shadow-release dark:border-white/10 dark:bg-[#262626]">
      <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-black/45 dark:text-white/45">
        {step}
      </span>
      <h4 className="mt-4 font-serif text-2xl leading-tight text-ink dark:text-paper">
        {title}
      </h4>
      <p className="mt-2 text-sm leading-relaxed text-black/60 dark:text-white/60">
        {description}
      </p>
    </div>
  );
}

function FeatureCard({
  title,
  bullets,
}: {
  title: string;
  bullets: string[];
}) {
  return (
    <div className="rounded-[1.5rem] border border-black/10 bg-white p-6 shadow-skill transition-all duration-200 ease-[cubic-bezier(0.215,0.61,0.355,1)] hover:shadow-release dark:border-white/10 dark:bg-[#262626]">
      <h4 className="font-serif text-2xl leading-tight text-ink dark:text-paper">
        {title}
      </h4>
      <ul className="mt-5 space-y-2 text-sm text-black/70 dark:text-white/70">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2">
            <span className="mt-[0.5rem] h-1 w-1 rounded-full bg-[#FA3D1D]" />
            {b}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FAQ({ q, a }: { q: string; a: string }) {
  return (
    <div className="rounded-[1.5rem] border border-black/10 bg-white p-6 shadow-skill dark:border-white/10 dark:bg-[#262626]">
      <h4 className="font-serif text-xl leading-tight text-ink dark:text-paper">
        {q}
      </h4>
      <p className="mt-3 text-sm leading-relaxed text-black/60 dark:text-white/60">
        {a}
      </p>
    </div>
  );
}
