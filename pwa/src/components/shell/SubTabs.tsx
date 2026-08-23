"use client";

type SubTab = {
  id: string;
  label: string;
};

type SubTabsProps = {
  tabs: readonly SubTab[];
  activeId: string;
  onChange: (id: string) => void;
};

export function SubTabs({ tabs, activeId, onChange }: SubTabsProps) {
  return (
    <div
      className="mb-5 flex flex-wrap gap-1 border-b border-[var(--hirio-line)]"
      role="tablist"
    >
      {tabs.map((tab) => {
        const active = tab.id === activeId;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={`-mb-px rounded-t-md px-4 py-2.5 text-sm transition-colors ${
              active
                ? "border border-b-[var(--hirio-surface)] border-[var(--hirio-line)] bg-[var(--hirio-surface)] font-medium text-[var(--hirio-ink)]"
                : "border border-transparent text-[var(--hirio-muted)] hover:text-[var(--hirio-ink)]"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
