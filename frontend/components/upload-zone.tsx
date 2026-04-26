"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, FileUp, Loader2, UploadCloud } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { uploadReport } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";

const MAX_MB = 50;

type Phase = "idle" | "uploading" | "analyzing" | "done" | "error";

export function UploadZone() {
  const router = useRouter();
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [progress, setProgress] = React.useState(0);
  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [dragActive, setDragActive] = React.useState(false);

  const onFile = React.useCallback(async (picked: File) => {
    setError(null);
    if (!picked.name.toLowerCase().endsWith(".pdf")) {
      const msg = "Only PDF files are supported.";
      setError(msg);
      toast.error(msg);
      return;
    }
    if (picked.size > MAX_MB * 1024 * 1024) {
      const msg = `File exceeds the ${MAX_MB}MB limit.`;
      setError(msg);
      toast.error(msg);
      return;
    }
    setFile(picked);
    setPhase("uploading");
    setProgress(0);
    try {
      const res = await uploadReport(picked, (pct) => {
        setProgress(pct);
        if (pct >= 100) setPhase("analyzing");
      });
      setPhase("done");
      toast.success(
        res.status === "ready"
          ? "Report analyzed — opening dashboard"
          : "Validation complete — embedding in the background",
      );
      router.push(`/report/${res.id}`);
    } catch (e: any) {
      const msg = e?.message ?? "Upload failed.";
      setError(msg);
      setPhase("error");
      toast.error(msg);
    }
  }, [router]);

  const handleDrop = React.useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      const f = e.dataTransfer.files?.[0];
      if (f) onFile(f);
    },
    [onFile]
  );

  const busy = phase === "uploading" || phase === "analyzing";

  return (
    <div id="upload" className="w-full">
      <div
        onDragEnter={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragActive(false);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        className={cn(
          "relative flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-black/12 bg-white px-8 py-14 text-center transition-all duration-200 ease-[cubic-bezier(0.215,0.61,0.355,1)]",
          "shadow-offset dark:bg-[#262626] dark:border-white/12",
          dragActive && "bg-[#FA3D1D]/5 border-[#FA3D1D]/60 scale-[1.005]"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />

        {phase === "idle" || phase === "error" ? (
          <>
            <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.18em] text-black/60 dark:text-white/60">
              Upload &middot; PDF
            </div>
            <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-[#FA3D1D]/10 text-[#FA3D1D]">
              <UploadCloud className="h-7 w-7" strokeWidth={1.75} />
            </div>
            <h3 className="font-serif text-2xl leading-tight text-ink dark:text-paper md:text-3xl">
              Drop your SOC 2 report here.
            </h3>
            <p className="mx-auto mt-2 max-w-md text-sm text-black/60 dark:text-white/60">
              PDF only &middot; up to {MAX_MB}MB &middot; Type I or Type II. We&apos;ll
              extract metadata, flag issues, and generate review questions.
            </p>
            <Button
              className="mt-6"
              variant="pill"
              size="pill"
              onClick={() => inputRef.current?.click()}
            >
              <FileUp className="mr-2 h-3.5 w-3.5" />
              Choose PDF
            </Button>
            {error && (
              <div className="mt-4 flex items-center gap-2 text-sm text-[#FA3D1D]">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
          </>
        ) : (
          <div className="w-full max-w-md">
            <div className="flex items-center gap-3">
              {phase === "done" ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-[#FA3D1D]" />
              )}
              <div className="flex-1 text-left">
                <div className="truncate text-sm font-medium text-ink dark:text-paper">
                  {file?.name ?? "Uploading"}
                </div>
                <div className="text-xs text-black/60 dark:text-white/60">
                  {file ? formatBytes(file.size) : null}
                  {file ? " · " : null}
                  {phase === "uploading" && `Uploading… ${progress}%`}
                  {phase === "analyzing" && "Parsing & validating…"}
                  {phase === "done" && "Ready — redirecting to dashboard"}
                </div>
              </div>
            </div>
            <Progress
              value={phase === "analyzing" ? 95 : progress}
              className="mt-4"
            />
            {busy && (
              <p className="mt-3 text-xs text-black/60 dark:text-white/60">
                This usually takes 5-20 seconds depending on report length.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="mt-6 grid gap-3 md:grid-cols-3">
        <Benefit title="Deterministic validation" detail="Regex + heuristics identify missing sections, stale reports, and opinion types." />
        <Benefit title="Grounded chat" detail="Ask questions and get answers citing exact report excerpts — never fabricated." />
        <Benefit title="Private by design" detail="Reports can be deleted at any time. Chunks and embeddings purge with them." />
      </div>
    </div>
  );
}

function Benefit({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-[1.5rem] border border-black/10 bg-white p-4 shadow-skill dark:border-white/10 dark:bg-[#262626]">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-black/60 dark:text-white/60">
        {title}
      </div>
      <div className="mt-2 text-sm leading-relaxed text-black/70 dark:text-white/70">
        {detail}
      </div>
    </div>
  );
}
