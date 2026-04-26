"use client";

import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-black/5 bg-[#DDDDDD]/[0.77] backdrop-blur supports-[backdrop-filter]:bg-[#DDDDDD]/[0.77] dark:border-white/5 dark:bg-[#1B1B1B]/80">
      <div className="container flex h-16 items-center justify-between">
        <Link
          href="/"
          className="font-serif text-[20px] leading-none tracking-tight text-ink transition-opacity hover:opacity-80 dark:text-paper"
        >
          SOC 2 Reviewer
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          <Link
            href="/#how-it-works"
            className="font-mono text-[12px] uppercase tracking-[0.08em] text-black/60 transition-colors hover:text-black dark:text-white/60 dark:hover:text-white"
          >
            How it works
          </Link>
          <Link
            href="/#features"
            className="font-mono text-[12px] uppercase tracking-[0.08em] text-black/60 transition-colors hover:text-black dark:text-white/60 dark:hover:text-white"
          >
            Features
          </Link>
          <Link
            href="/#faq"
            className="font-mono text-[12px] uppercase tracking-[0.08em] text-black/60 transition-colors hover:text-black dark:text-white/60 dark:hover:text-white"
          >
            FAQ
          </Link>
        </nav>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button variant="pill" size="pill" asChild>
            <Link href="/#upload">Upload report</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
