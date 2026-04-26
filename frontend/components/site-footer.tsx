export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-black/10 bg-paper dark:border-white/10 dark:bg-[#1B1B1B]">
      <div className="container flex flex-col items-start justify-between gap-3 py-8 md:flex-row md:items-center">
        <span className="font-serif text-[18px] leading-none text-ink dark:text-paper">
          SOC 2 Reviewer
        </span>
        <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-black/50 dark:text-white/50">
          &copy; {new Date().getFullYear()} &middot; All rights reserved
        </span>
      </div>
    </footer>
  );
}
