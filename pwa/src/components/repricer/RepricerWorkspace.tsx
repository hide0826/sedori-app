"use client";

import { useState } from "react";
import { SubTabs } from "@/components/shell/SubTabs";
import RepricerSettingsTable from "@/app/components/RepricerSettingsTable";
import { DummyRepricerCsvDownload } from "@/components/repricer/DummyRepricerCsvDownload";
import { SpApiRepricerPanel } from "@/components/repricer/SpApiRepricerPanel";

const REPRICER_SUB_TABS = [
  { id: "run", label: "改定実行" },
  { id: "rules", label: "改定ルール" },
  { id: "sp-api", label: "SP-API改定" },
] as const;

type SubTabId = (typeof REPRICER_SUB_TABS)[number]["id"];

export function RepricerWorkspace() {
  const [active, setActive] = useState<SubTabId>("run");

  return (
    <div>
      <SubTabs
        tabs={REPRICER_SUB_TABS}
        activeId={active}
        onChange={(id) => setActive(id as SubTabId)}
      />

      {active === "run" && (
        <div>
          <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
            <p className="font-medium">ダミーデータで試す手順</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-[var(--hirio-muted)]">
              <li>
                <DummyRepricerCsvDownload />
              </li>
              <li>下の「CSVファイルを選択」でそのファイルを選ぶ</li>
              <li>まず「プレビュー」で結果を確認（おすすめ）</li>
              <li>必要なら「適用」もダミー上だけで試せる</li>
            </ol>
          </section>
          <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
            <RepricerSettingsTable panel="run" />
          </div>
        </div>
      )}

      {active === "rules" && (
        <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
          <RepricerSettingsTable panel="rules" />
        </div>
      )}

      {active === "sp-api" && <SpApiRepricerPanel />}
    </div>
  );
}
