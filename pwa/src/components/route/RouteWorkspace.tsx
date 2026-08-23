"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import { ROUTE_MENU } from "@/components/menus/menuDummyData";
import {
  fetchRouteSummariesFromApi,
  fetchRouteVisitsFromApi,
  formatTimeShort,
  formatYen,
  type RouteDataSource,
  type RouteSummary,
  type RouteVisit,
} from "@/lib/routes-api";

const ROUTE_SUB_TABS = [
  { id: "select", label: "ルート選択" },
  { id: "summary", label: "ルートサマリー" },
] as const;

type SubTabId = (typeof ROUTE_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<RouteDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

function dummySummaries(): RouteSummary[] {
  const selectTab = ROUTE_MENU.tabs.find((t) => t.id === "select");
  if (!selectTab) return [];
  return selectTab.rows.map((row, index) => ({
    id: index + 1,
    route_date: String(row.date ?? ""),
    route_code: null,
    route_display_name: String(row.route ?? ""),
    departure_time: null,
    return_time: null,
    store_count: Number(row.stores ?? 0),
    total_item_count: null,
    total_gross_profit: null,
    estimated_hourly_rate: null,
    listing_completed: row.status === "完了",
    evidence_completed: row.status === "完了",
    images_completed: row.status === "完了",
    status_label: String(row.status ?? "—"),
    updated_at: null,
  }));
}

function dummyVisits(): RouteVisit[] {
  const summaryTab = ROUTE_MENU.tabs.find((t) => t.id === "summary");
  if (!summaryTab) return [];
  return summaryTab.rows.map((row, index) => ({
    id: index + 1,
    store_code: String(row.store ?? ""),
    visit_order: index + 1,
    store_in_time: String(row.in ?? ""),
    store_out_time: String(row.out ?? ""),
    stay_duration: null,
    store_item_count: Number(row.purchases ?? 0),
    store_gross_profit: null,
    store_notes: String(row.memo ?? ""),
    purchase_success: Number(row.purchases ?? 0) > 0,
  }));
}

/**
 * ルート選択・ルートサマリー。
 * API（hirio.db）を優先し、失敗時はダミー表にフォールバックする。
 */
export function RouteWorkspace() {
  const [active, setActive] = useState<SubTabId>("select");
  const [source, setSource] = useState<RouteDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<RouteSummary[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [visits, setVisits] = useState<RouteVisit[]>([]);
  const [visitRouteLabel, setVisitRouteLabel] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [visitsLoading, setVisitsLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const selectedSummary = useMemo(
    () => summaries.find((s) => s.id === selectedRouteId) ?? null,
    [summaries, selectedRouteId]
  );

  const loadSummaries = useCallback(async () => {
    setLoading(true);
    const api = await fetchRouteSummariesFromApi();
    if (api.ok && api.data) {
      setSummaries(api.data.summaries);
      setSource("server_db");
      setDbPath(api.data.db_path ?? null);
      if (api.data.summaries.length > 0) {
        setSelectedRouteId((prev) =>
          prev && api.data!.summaries.some((s) => s.id === prev)
            ? prev
            : api.data!.summaries[0].id
        );
      }
      setLoading(false);
      return;
    }

    const dummy = dummySummaries();
    setSummaries(dummy);
    setSource("dummy");
    setDbPath(null);
    if (dummy.length > 0) {
      setSelectedRouteId(dummy[0].id);
    }
    setMessage(api.message ?? "API に接続できませんでした");
    setLoading(false);
  }, []);

  const loadVisits = useCallback(
    async (routeId: number) => {
      if (source === "dummy") {
        setVisits(dummyVisits());
        setVisitRouteLabel("（ダミー）");
        return;
      }

      setVisitsLoading(true);
      const api = await fetchRouteVisitsFromApi(routeId);
      if (api.ok && api.data) {
        setVisits(api.data.visits);
        const label = [api.data.route_date, api.data.route_display_name]
          .filter(Boolean)
          .join(" ");
        setVisitRouteLabel(label || `ルート #${routeId}`);
        setVisitsLoading(false);
        return;
      }

      setVisits([]);
      setVisitRouteLabel("");
      setMessage(api.message ?? "店舗訪問の取得に失敗しました");
      setVisitsLoading(false);
    },
    [source]
  );

  useEffect(() => {
    void loadSummaries();
  }, [loadSummaries]);

  useEffect(() => {
    if (selectedRouteId != null) {
      void loadVisits(selectedRouteId);
    }
  }, [selectedRouteId, loadVisits]);

  const incompleteCount = summaries.filter(
    (s) => !(s.listing_completed && s.evidence_completed && s.images_completed)
  ).length;

  return (
    <div>
      <PageHeader
        title="ルート"
        description="デスクトップの「ルート選択」「ルートサマリー」をブラウザで閲覧します（読み取り専用）。"
      />

      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">読み込み元: {SOURCE_LABEL[source]}</p>
        {dbPath && (
          <p className="mt-1 break-all text-xs text-[var(--hirio-muted)]">{dbPath}</p>
        )}
        {message && (
          <p className="mt-2 text-xs text-amber-700">{message}</p>
        )}
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={ROUTE_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {active === "select" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              直近のルート一覧です。行をクリックすると「ルートサマリー」タブで IN/OUT を表示します。
            </p>

            {!loading && summaries.length > 0 && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg bg-[var(--hirio-surface)] px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">表示件数</div>
                  <div className="mt-1 text-xl font-semibold">{summaries.length}</div>
                </div>
                <div className="rounded-lg bg-amber-50 px-4 py-3 text-center text-amber-800">
                  <div className="text-xs opacity-80">未完了</div>
                  <div className="mt-1 text-xl font-semibold">{incompleteCount}</div>
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
                      <th className="px-2 py-2 font-medium">日付</th>
                      <th className="px-2 py-2 font-medium">ルート名</th>
                      <th className="px-2 py-2 text-right font-medium">店舗数</th>
                      <th className="px-2 py-2 text-right font-medium">仕入件数</th>
                      <th className="px-2 py-2 font-medium">状態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summaries.map((row) => {
                      const selected = row.id === selectedRouteId;
                      return (
                        <tr
                          key={row.id}
                          className={`cursor-pointer border-b border-[var(--hirio-line)] ${
                            selected ? "bg-[var(--hirio-accent-soft)]" : "hover:bg-slate-50"
                          }`}
                          onClick={() => {
                            setSelectedRouteId(row.id);
                            setActive("summary");
                          }}
                        >
                          <td className="px-2 py-2">{row.route_date ?? "—"}</td>
                          <td className="px-2 py-2">{row.route_display_name || row.route_code || "—"}</td>
                          <td className="px-2 py-2 text-right">{row.store_count}</td>
                          <td className="px-2 py-2 text-right">{row.total_item_count ?? "—"}</td>
                          <td className="px-2 py-2">{row.status_label}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "summary" && (
          <div>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <label className="text-sm text-[var(--hirio-muted)]">
                ルート
                <select
                  className="ml-2 rounded border border-[var(--hirio-line)] bg-white px-2 py-1 text-sm text-[var(--hirio-ink)]"
                  value={selectedRouteId ?? ""}
                  onChange={(e) => setSelectedRouteId(Number(e.target.value))}
                  disabled={summaries.length === 0}
                >
                  {summaries.map((s) => (
                    <option key={s.id} value={s.id}>
                      {[s.route_date, s.route_display_name || s.route_code]
                        .filter(Boolean)
                        .join(" ")}
                    </option>
                  ))}
                </select>
              </label>
              {selectedSummary && (
                <span className="text-xs text-[var(--hirio-muted)]">
                  粗利 {formatYen(selectedSummary.total_gross_profit)} /
                  時給 {formatYen(selectedSummary.estimated_hourly_rate)}
                </span>
              )}
            </div>

            {visitRouteLabel && (
              <p className="mb-3 text-sm text-[var(--hirio-muted)]">{visitRouteLabel}</p>
            )}

            {visitsLoading ? (
              <p className="text-sm text-[var(--hirio-muted)]">店舗訪問を読み込み中…</p>
            ) : visits.length === 0 ? (
              <p className="text-sm text-[var(--hirio-muted)]">店舗訪問データがありません。</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">店舗</th>
                      <th className="px-2 py-2 font-medium">IN</th>
                      <th className="px-2 py-2 font-medium">OUT</th>
                      <th className="px-2 py-2 text-right font-medium">仕入件数</th>
                      <th className="px-2 py-2 text-right font-medium">粗利</th>
                      <th className="px-2 py-2 font-medium">メモ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visits.map((visit) => (
                      <tr key={visit.id ?? visit.store_code} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{visit.store_code ?? "—"}</td>
                        <td className="px-2 py-2">{formatTimeShort(visit.store_in_time)}</td>
                        <td className="px-2 py-2">{formatTimeShort(visit.store_out_time)}</td>
                        <td className="px-2 py-2 text-right">{visit.store_item_count ?? "—"}</td>
                        <td className="px-2 py-2 text-right">{formatYen(visit.store_gross_profit)}</td>
                        <td className="px-2 py-2">{visit.store_notes ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-[var(--hirio-muted)]">
          読み取り専用です。編集・保存はデスクトップ側が正です。
        </p>
      </div>
    </div>
  );
}
