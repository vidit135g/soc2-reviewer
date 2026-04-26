"use client";

import * as React from "react";
import { Bot, Loader2, Send, Sparkles, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { getChatHistory, postChatMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatCitation, ChatMessage, Confidence } from "@/types";

interface Props {
  reportId: string;
  seed?: string | null;
  onSeedConsumed?: () => void;
}

interface UiMessage extends ChatMessage {
  confidence?: Confidence;
  citationsResolved?: ChatCitation[];
  pending?: boolean;
}

export function ChatInterface({ reportId, seed, onSeedConsumed }: Props) {
  const [messages, setMessages] = React.useState<UiMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  // Load history
  React.useEffect(() => {
    let cancelled = false;
    getChatHistory(reportId)
      .then((h) => {
        if (cancelled) return;
        setMessages(h);
      })
      .catch(() => {
        /* ignore — fresh chat */
      })
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const send = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;
      setSending(true);
      const userMsg: UiMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        content: trimmed,
        created_at: new Date().toISOString(),
      };
      const placeholder: UiMessage = {
        id: `pending-${Date.now()}`,
        role: "assistant",
        content: "",
        created_at: new Date().toISOString(),
        pending: true,
      };
      setMessages((prev) => [...prev, userMsg, placeholder]);
      setInput("");
      try {
        const res = await postChatMessage(reportId, trimmed);
        setMessages((prev) => {
          const next = [...prev];
          // Replace the pending placeholder
          const idx = next.findIndex((m) => m.id === placeholder.id);
          if (idx >= 0) {
            next[idx] = {
              ...res.message,
              confidence: res.confidence,
              citationsResolved: res.citations,
            };
          }
          return next;
        });
      } catch (e: any) {
        setMessages((prev) => prev.filter((m) => m.id !== placeholder.id));
        toast.error(e?.message ?? "Chat failed");
      } finally {
        setSending(false);
      }
    },
    [reportId, sending]
  );

  React.useEffect(() => {
    if (seed && loaded && !sending) {
      send(seed);
      onSeedConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, loaded]);

  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, sending]);

  return (
    <Card className="flex h-[calc(100vh-280px)] min-h-[520px] flex-col overflow-hidden">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-smooth-custom p-4 md:p-6"
      >
        {messages.length === 0 ? (
          <EmptyState onAsk={(q) => send(q)} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.map((m) => (
              <Message key={m.id} message={m} />
            ))}
          </div>
        )}
      </div>

      <div className="border-t bg-card p-3 md:p-4">
        <div className="mx-auto max-w-3xl">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex items-end gap-2"
          >
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              placeholder="Ask about the report — e.g. 'Were any access-control exceptions noted?'"
              rows={2}
              className="flex-1"
              disabled={sending}
            />
            <Button type="submit" size="icon" className="h-10 w-10 shrink-0" disabled={sending || !input.trim()}>
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Responses are grounded in your uploaded report. If the report doesn&apos;t cover a topic,
            the assistant will say so.
          </p>
        </div>
      </div>
    </Card>
  );
}

function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
  const presets = [
    "Summarize the auditor's opinion and scope.",
    "Were any exceptions identified during testing?",
    "Is multi-factor authentication required for privileged access?",
    "List the subservice organizations and their role.",
  ];
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center justify-center py-10 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Sparkles className="h-6 w-6" />
      </div>
      <h3 className="mt-4 text-lg font-semibold">Ask anything about this report</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Answers cite specific excerpts and declare a confidence level. No hallucinations.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {presets.map((q) => (
          <Button key={q} variant="subtle" size="sm" onClick={() => onAsk(q)}>
            {q}
          </Button>
        ))}
      </div>
    </div>
  );
}

function Message({ message }: { message: UiMessage }) {
  const isUser = message.role === "user";
  const citations = message.citationsResolved ?? (message.citations as ChatCitation[] | undefined) ?? [];
  return (
    <div className={cn("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "group max-w-[85%] rounded-2xl px-4 py-3 text-sm shadow-soft",
          isUser
            ? "bg-primary text-primary-foreground"
            : "border bg-card text-foreground"
        )}
      >
        {message.pending ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" />
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current [animation-delay:0.2s]" />
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current [animation-delay:0.4s]" />
            Thinking…
          </span>
        ) : isUser ? (
          <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
        ) : (
          <>
            <article className="prose prose-sm max-w-none dark:prose-invert prose-p:my-2 prose-ul:my-2">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </article>
            {(message.confidence || citations.length > 0) && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {message.confidence && (
                  <Badge
                    variant={
                      message.confidence === "high"
                        ? "success"
                        : message.confidence === "medium"
                        ? "info"
                        : "warning"
                    }
                  >
                    Confidence: {message.confidence}
                  </Badge>
                )}
                {citations.length > 0 && (
                  <Badge variant="outline">
                    {citations.length} source{citations.length > 1 ? "s" : ""}
                  </Badge>
                )}
              </div>
            )}
            {citations.length > 0 && (
              <details className="mt-3 group/citations">
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  View sources
                </summary>
                <div className="mt-2 space-y-2">
                  {citations.map((c, i) => (
                    <div
                      key={c.chunk_id}
                      className="rounded-lg border bg-muted/40 p-2 text-xs"
                    >
                      <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>
                          [{i + 1}] {c.page_number ? `Page ${c.page_number}` : "Excerpt"}
                        </span>
                        <span>Relevance {(c.score * 100).toFixed(0)}%</span>
                      </div>
                      <p className="whitespace-pre-wrap leading-relaxed">{c.snippet}</p>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}
