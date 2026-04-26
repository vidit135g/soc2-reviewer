import Link from "next/link";
import { FileX } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="container flex flex-col items-center justify-center py-32 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
        <FileX className="h-7 w-7" />
      </div>
      <h1 className="mt-6 text-2xl font-semibold">Report not found</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        The report you&apos;re looking for doesn&apos;t exist or has been deleted.
      </p>
      <Button asChild className="mt-6">
        <Link href="/">Upload a new report</Link>
      </Button>
    </div>
  );
}
