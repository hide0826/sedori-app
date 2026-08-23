"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import { ANALYSIS_MENU } from "@/components/menus/menuDummyData";
import type { DbDataSource } from "@/lib/database-api";
import {
  fetchAnalysisSummaryFromApi,
  fetchStoreScoresFromApi,
  formatMetricValue,
  formatYen,
  type AnalysisMetric,
  type StoreScoreRow,
} from "@/lib/analysis-api";

const ANALYSIS_SUB_TABS = [
  { id: "stats", label: "基本統計" },
  { id: "stores", label: "店舗スコア" },
] as const;

type SubTabId = (typeof ANALYSIS_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<DbDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

export function AnalysisWorkspace() {
  const [active, setActive] = useState<SubTabId>("stats");
  const [source, setSource] = useState<DbDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<AnalysisMetric[]>([]);
  const [storeCount, setStoreCount] = useState(0);
  const [days, setDays] = useState(30);
  const [stores, setStores] = useState<StoreScoreRow[]>([]);
  const [storeTotal, setStoreTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    const [summaryRes, scoresRes] = await Promise.all([
      fetchAnalysisSummaryFromApi(),
      fetchStoreScoresFromApi(),
    ]);

    const errors: string[] = [];

    if (summaryRes.ok && summaryRes.data) {
      setMetrics(summaryRes.data.metrics);
      setStoreCount(summaryRes.data.store_count);
      setDays(summaryRes.data.days);
      setSource("server_db");
      setDbPath(summaryRes.data.db_path ?? null);
    } else {
      const tab = ANALYSIS_MENU.tabs.find((t) => t.id === "stats");
      setMetrics(
        (tab?.rows ?? []).map((row) => ({
          metric: String(row.metric ?? ""),
          value: typeof row.value === "number" ? row.value : 0,
          note: String(row.note ?? ""),
        }))
      );
      setStoreCount(Number(tab?.summary?.[1]?.value ?? 0));
      errors.push(summaryRes.message ?? "基本統計 API に接続できませんでした");
    }

    if (scoresRes.ok && scoresRes.data) {
      setStores(scoresRes.data.stores);
      setStoreTotal(scoresRes.data.total);
      if (summaryRes.ok) {
        setSource("server_db");
        setDbPath((prev) => prev ?? scoresRes.data?.db_path ?? null);
      }
    } else {
      const tab = ANALYSIS_MENU.tabs.find((t) => t.id === "stores");
      setStores(
        (tab?.rows ?? []).map((row) => ({
          store_code: "",
          store_name: String(row.store ?? ""),
          score: Number(row.score ?? 0),
          hourly_estimate: 0,
          visit_count: 0,
          total_gross_profit: 0,
          trend: String(row.trend ?? "—"),
        }))
      );
      setStoreTotal((tab?.rows ?? []).length);
      errors.push(scoresRes.message ?? "店舗スコア API に接続できませんでした");
    }

    if (errors.length === 2) {
      setSource("dummy");
      setDbPath(null);
    }
    if (errors.length > 0) {
      setMessage(errors.join(" / "));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  return (
    <div>
      <PageHeader
        title="分析"
        description="仕入・店舗訪問データから基本統計と店舗スコアを表示します（読み取り専用）。"
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
          tabs={ANALYSIS_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {active === "stats" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              直近 {days} 日の商品DB集計です。
            </p>

            {!loading && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3">
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">対象期間</div>
                  <div className="mt-1 text-xl font-semibold">{days}日</div>
                </div>
                <div className="rounded-lg bg-[var(--hirio-accent-soft)] px-4 py-3 text-center text-[var(--hirio-ok)]">
                  <div className="text-xs opacity-80">店舗数</div>
                  <div className="mt-1 text-xl font-semibold">{storeCount}</div>
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
                      <th className="px-2 py-2 font-medium">指標</th>
                      <th className="px-2 py-2 text-right font-medium">値</th>
                      <th className="px-2 py-2 font-medium">メモ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.map((row) => (
                      <tr key={row.metric} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{row.metric}</td>
                        <td className="px-2 py-2 text-right">
                          {formatMetricValue(row.metric, row.value)}
                        </td>
                        <td className="px-2 py-2">{row.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "stores" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              ルート訪問ログから粗利順に {stores.length} 店舗を表示（全体 {storeTotal} 店舗）。
            </p>

            {loading ? (
              <p className="text-sm text-[var(--hirio-muted)]">読み込み中…</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">店舗</th>
                      <th className="px-2 py-2 text-right font-medium">スコア</th>
                      <th className="px-2 py-2 text-right font-medium">粗利/訪問</th>
                      <th className="px-2 py-2 text-right font-medium">訪問数</th>
                      <th className="px-2 py-2 font-medium">傾向</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stores.map((row) => (
                      <tr key={row.store_code || row.store_name} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{row.store_name || row.store_code}</td>
                        <td className="px-2 py-2 text-right">{row.score}</td>
                        <td className="px-2 py-2 text-right">
                          {formatYen(row.hourly_estimate)}
                        </td>
                        <td className="px-2 py-2 text-right">{row.visit_count}</td>
                        <td className="px-2 py-2">{row.trend}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-[var(--hirio-muted)]">
          簡易集計です。詳細分析はデスクトップ側が正です。
        </p>
      </div>
    </div>
  );
}
