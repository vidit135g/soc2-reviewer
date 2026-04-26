"use client";

import * as React from "react";
import { Loader2, MessageSquareMore, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSuggestedQuestions } from "@/lib/api";

export function SuggestedQuestions({
  reportId,
  onAsk,
}: {
  reportId: string;
  onAsk: (q: string) => void;
}) {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [questions, setQuestions] = React.useState<string[]>([]);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSuggestedQuestions(reportId)
      .then((res) => {
        if (cancelled) return;
        setQuestions(res.questions);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message ?? "Failed to generate questions");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          Suggested review questions
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Click any question to ask the chat assistant. Answers cite exact excerpts from the report.
        </p>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Generating questions…
          </div>
        ) : error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {questions.map((q) => (
              <Button
                key={q}
                variant="subtle"
                size="sm"
                className="h-auto whitespace-normal py-2 text-left"
                onClick={() => onAsk(q)}
              >
                <MessageSquareMore className="mr-2 h-3.5 w-3.5 shrink-0" />
                <span>{q}</span>
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
