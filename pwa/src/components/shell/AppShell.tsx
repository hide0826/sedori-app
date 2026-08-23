"use client";

import { useState } from "react";
import { Sidebar } from "./Sidebar";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-[var(--hirio-bg)]">
      <Sidebar open={open} onClose={() => setOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-[var(--hirio-line)] bg-[var(--hirio-surface)] px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded-md border border-[var(--hirio-line)] px-3 py-1.5 text-sm"
            aria-label="メニューを開く"
          >
            メニュー
          </button>
          <span className="text-lg font-semibold tracking-wide">HIRIO</span>
        </header>

        <main className="flex-1 px-4 py-5 md:px-8 md:py-7">{children}</main>
      </div>
    </div>
  );
}
