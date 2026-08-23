"use client";

import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import type { ThinMenuConfig } from "@/components/menus/menuDummyData";

type ThinMenuWorkspaceProps = {
  config: ThinMenuConfig;
};

const toneClass = {
  default: "bg-[var(--hirio-surface)] text-[var(--hirio-ink)]",
  ok: "bg-[var(--hirio-accent-soft)] text-[var(--hirio-ok)]",
  warn: "bg-amber-50 text-amber-800",
} as const;

/**
 * 他メニュー共通の薄いPWA版。
 * サブタブ＋ダミー表＋説明。本番DB/APIには未接続。
 */
export function ThinMenuWorkspace({ config }: ThinMenuWorkspaceProps) {
  const [active, setActive] = useState(config.tabs[0]?.id ?? "");
  const tab =
    config.tabs.find((t) => t.id === active) ?? config.tabs[0] ?? null;

  if (!tab) return null;

  return (
    <div>
      <PageHeader title={config.title} description={config.description} />

      {config.note && (
        <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
          <p className="font-medium">ダミー前提</p>
          <p className="mt-1 text-[var(--hirio-muted)]">{config.note}</p>
        </section>
      )}

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={config.tabs.map((t) => ({ id: t.id, label: t.label }))}
          activeId={active}
          onChange={setActive}
        />

        {tab.hint && (
          <p className="mb-4 text-sm text-[var(--hirio-muted)]">{tab.hint}</p>
        )}

        {tab.summary && tab.summary.length > 0 && (
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            {tab.summary.map((card) => (
              <div
                key={card.label}
                className={`rounded-lg px-4 py-3 text-center ${toneClass[card.tone ?? "default"]}`}
              >
                <div className="text-xs text-[var(--hirio-muted)]">
                  {card.label}
                </div>
                <div className="mt-1 text-xl font-semibold">{card.value}</div>
              </div>
            ))}
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                {tab.columns.map((col) => (
                  <th
                    key={col.key}
                    className={`px-2 py-2 font-medium ${
                      col.align === "right" ? "text-right" : ""
                    }`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tab.rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-[var(--hirio-line)]"
                >
                  {tab.columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-2 py-2 ${
                        col.align === "right" ? "text-right" : ""
                      } ${col.key === "sku" ? "font-mono text-xs" : ""}`}
                    >
                      {row[col.key] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-4 text-xs text-[var(--hirio-muted)]">
          本番データはデスクトップ側が正です。PWA は枠とダミー表示のみです。
        </p>
      </div>
    </div>
  );
}
