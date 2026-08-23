"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import { ANTIQUE_MENU } from "@/components/menus/menuDummyData";
import {
  fetchLedgerEntriesFromApi,
  formatYen,
  type LedgerEntry,
} from "@/lib/ledger-api";
import type { DbDataSource } from "@/lib/database-api";

const ANTIQUE_SUB_TABS = [
  { id: "ledger", label: "閲覧・出力" },
  { id: "input", label: "入力・生成" },
] as const;

type SubTabId = (typeof ANTIQUE_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<DbDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

function dummyEntries(): LedgerEntry[] {
  const tab = ANTIQUE_MENU.tabs.find((t) => t.id === "ledger");
  if (!tab) return [];
  return tab.rows.map((row, index) => ({
    id: index + 1,
    entry_date: String(row.date ?? ""),
    hinmei: String(row.name ?? ""),
    feature: String(row.feature ?? ""),
    counterparty_name: String(row.seller ?? ""),
    amount: Number(row.price ?? 0),
    qty: 1,
    sku: "",
  }));
}

export function AntiqueWorkspace() {
  const [active, setActive] = useState<SubTabId>("ledger");
  const [source, setSource] = useState<DbDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const inputTab = ANTIQUE_MENU.tabs.find((t) => t.id === "input");

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    const res = await fetchLedgerEntriesFromApi();
    if (res.ok && res.data) {
      setEntries(res.data.entries);
      setTotal(res.data.total);
      setSource("server_db");
      setDbPath(res.data.db_path ?? null);
    } else {
      setEntries(dummyEntries());
      setTotal(dummyEntries().length);
      setSource("dummy");
      setDbPath(null);
      setMessage(res.message ?? "古物台帳 API に接続できませんでした");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  return (
    <div>
      <PageHeader
        title="古物台帳"
        description="確定済みの古物台帳をブラウザで閲覧します（読み取り専用）。入力・PDF出力はデスクトップが正です。"
      />

      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">読み込み元: {SOURCE_LABEL[source]}</p>
        {dbPath && (
          <p className="mt-1 break-all text-xs text-[var(--hirio-muted)]">{dbPath}</p>
        )}
        {message && <p className="mt-2 text-xs text-amber-700">{message}</p>}
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={ANTIQUE_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {active === "ledger" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              直近 {entries.length} 件を表示します（全体 {total} 件）。
            </p>

            {!loading && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">表示件数</div>
                  <div className="mt-1 text-xl font-semibold">{entries.length}</div>
                </div>
                <div className="rounded-lg bg-[var(--hirio-accent-soft)] px-4 py-3 text-center text-[var(--hirio-ok)]">
                  <div className="text-xs opacity-80">台帳総数</div>
                  <div className="mt-1 text-xl font-semibold">{total}</div>
                </div>
              </div>
            )}

            {loading ? (
              <p className="text-sm text-[var(--hirio-muted)]">読み込み中…</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">受入日</th>
                      <th className="px-2 py-2 font-medium">品名</th>
                      <th className="px-2 py-2 font-medium">特徴</th>
                      <th className="px-2 py-2 font-medium">売主</th>
                      <th className="px-2 py-2 text-right font-medium">代価</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((row) => (
                      <tr key={row.id ?? row.entry_date} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{row.entry_date ?? "—"}</td>
                        <td className="px-2 py-2">{row.hinmei || "—"}</td>
                        <td className="px-2 py-2">{row.feature || "—"}</td>
                        <td className="px-2 py-2">{row.counterparty_name || "—"}</td>
                        <td className="px-2 py-2 text-right">{formatYen(row.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "input" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              入力・生成・PDF/CSV 出力はデスクトップ側で行います。
            </p>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                    {inputTab?.columns.map((col) => (
                      <th key={col.key} className="px-2 py-2 font-medium">
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {inputTab?.rows.map((row, i) => (
                    <tr key={i} className="border-b border-[var(--hirio-line)]">
                      {inputTab.columns.map((col) => (
                        <td key={col.key} className="px-2 py-2">
                          {row[col.key] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <p className="mt-4 text-xs text-[var(--hirio-muted)]">
          読み取り専用です。編集・出力はデスクトップ側が正です。
        </p>
      </div>
    </div>
  );
}
