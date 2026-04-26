import { Loader2 } from "lucide-react";

export default function Loading() {
  return (
    <div className="container flex flex-col items-center justify-center py-32 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="mt-4 text-sm text-muted-foreground">Loading report…</p>
    </div>
  );
}
