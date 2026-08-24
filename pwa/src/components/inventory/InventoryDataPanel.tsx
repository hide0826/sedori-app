"use client";

import React, { useEffect, useState } from "react";
import CsvUploader from "@/app/components/CsvUploader";
import InventoryDataGrid from "@/app/components/InventoryDataGrid";
import { InventoryItem } from "@/types/repricer";
import { getApiBaseUrl } from "@/lib/api-config";
import { DummyInventoryCsvDownload } from "@/components/inventory/DummyInventoryCsvDownload";
import {
  fetchRouteSummariesFromApi,
  formatTimeShort,
  formatYen,
  type RouteSummary,
} from "@/lib/routes-api";
import {
  fetchRouteTemplateFromApi,
  inventoryItemToPurchaseRecord,
  matchStoresFromData,
  purchaseRecordToInventoryItem,
  saveInventoryToDb,
  type RouteTemplateSummary,
  type RouteTemplateVisit,
} from "@/lib/inventory-api";

const WORKFLOW_STEPS = [
  "①CSV取込",
  "②ルートテンプレ読込",
  "③照合処理実行",
  "④SKU生成",
  "⑤コンディション説明編集",
  "⑥DB保存",
  "⑦古物台帳生成",
  "⑧出品CSV生成",
] as const;

/**
 * 仕入管理「仕入データ」サブタブの中身。
 * デスクトップと同じ流れ: CSV → ルートテンプレ → 照合 → SKU → DB保存 → 出品CSV。
 */
export function InventoryDataPanel() {
  const [inventoryData, setInventoryData] = useState<InventoryItem[]>([]);
  const [isGeneratingSku, setIsGeneratingSku] = useState(false);
  const [skuError, setSkuError] = useState<string | null>(null);
  const [skuSuccess, setSkuSuccess] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);
  const [routes, setRoutes] = useState<RouteSummary[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [timeTolerance, setTimeTolerance] = useState(1);
  const [isMatching, setIsMatching] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [matchSuccess, setMatchSuccess] = useState<string | null>(null);
  const [isLoadingTemplate, setIsLoadingTemplate] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templateSuccess, setTemplateSuccess] = useState<string | null>(null);
  const [loadedRouteId, setLoadedRouteId] = useState<number | null>(null);
  const [templateSummary, setTemplateSummary] =
    useState<RouteTemplateSummary | null>(null);
  const [templateVisits, setTemplateVisits] = useState<RouteTemplateVisit[]>(
    []
  );
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const res = await fetchRouteSummariesFromApi();
      if (res.ok && res.data && res.data.summaries.length > 0) {
        setRoutes(res.data.summaries);
        setSelectedRouteId(res.data.summaries[0].id);
      }
    })();
  }, []);

  const handleCsvUploadSuccess = (data: InventoryItem[]) => {
    setInventoryData(data);
    setSkuError(null);
    setSkuSuccess(null);
    setExportError(null);
    setExportSuccess(null);
    setMatchError(null);
    setMatchSuccess(null);
    setSaveError(null);
    setSaveSuccess(null);
  };

  const handleInventoryDataChange = (newData: InventoryItem[]) => {
    setInventoryData(newData);
  };

  const handleLoadRouteTemplate = async () => {
    if (selectedRouteId == null) {
      setTemplateError("ルートを選択してください");
      return;
    }

    setIsLoadingTemplate(true);
    setTemplateError(null);
    setTemplateSuccess(null);

    try {
      const result = await fetchRouteTemplateFromApi(selectedRouteId);
      if (!result.ok || !result.data) {
        throw new Error(result.message ?? "ルートテンプレの読み込みに失敗しました");
      }
      setTemplateSummary(result.data.summary);
      setTemplateVisits(result.data.visits);
      setLoadedRouteId(selectedRouteId);
      const label = [
        result.data.summary.route_date,
        result.data.summary.route_display_name,
      ]
        .filter(Boolean)
        .join(" ");
      setTemplateSuccess(
        `ルートテンプレ読込完了: ${label}（${result.data.count}店舗）`
      );
    } catch (error: unknown) {
      const message =
        error instanceof Error
          ? error.message
          : "ルートテンプレ読込中にエラーが発生しました";
      setTemplateError(message);
      setLoadedRouteId(null);
      setTemplateVisits([]);
      setTemplateSummary(null);
    } finally {
      setIsLoadingTemplate(false);
    }
  };

  const handleMatchStores = async () => {
    if (inventoryData.length === 0) return;
    if (selectedRouteId == null) {
      setMatchError("ルートを選択してください");
      return;
    }

    setIsMatching(true);
    setMatchError(null);
    setMatchSuccess(null);

    try {
      const purchaseData = inventoryData.map(inventoryItemToPurchaseRecord);
      const result = await matchStoresFromData(
        purchaseData,
        selectedRouteId,
        timeTolerance
      );

      if (!result.ok || !result.data) {
        throw new Error(result.message ?? "時刻突合に失敗しました");
      }

      const updated = result.data.data.map(purchaseRecordToInventoryItem);
      setInventoryData(updated);
      const { matched_rows, total_rows } = result.data.stats;
      setMatchSuccess(
        `照合完了: ${matched_rows} / ${total_rows} 件に店舗コードを付与しました`
      );
    } catch (error: unknown) {
      const message =
        error instanceof Error
          ? error.message
          : "照合処理中にエラーが発生しました";
      setMatchError(message);
    } finally {
      setIsMatching(false);
    }
  };

  const handleGenerateSKU = async () => {
    setIsGeneratingSku(true);
    setSkuError(null);
    setSkuSuccess(null);

    try {
      const requestData = {
        products: inventoryData.map((item) => ({
          jan: item.jan,
          asin: item.asin,
          product_name: item.productName,
          purchase_price: item.purchasePrice,
          condition: item.condition,
          supplier_code: item.supplier,
        })),
      };

      const response = await fetch(
        `${getApiBaseUrl()}/api/inventory/generate-sku-bulk`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer hirio-local-key",
          },
          body: JSON.stringify(requestData),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API Error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();

      if (!result.results || !Array.isArray(result.results)) {
        throw new Error("商品データが見つかりません");
      }

      const updatedData = inventoryData.map((item, index) => {
        const product = result.results[index] as { sku?: string } | undefined;
        if (!product?.sku) return item;
        return { ...item, sku: product.sku };
      });

      setInventoryData(updatedData);
      setSkuSuccess("SKU生成が完了しました！");
    } catch (error: unknown) {
      const message =
        error instanceof Error
          ? error.message
          : "SKU生成中にエラーが発生しました";
      setSkuError(message);
    } finally {
      setIsGeneratingSku(false);
    }
  };

  const handleSaveToDb = async () => {
    if (inventoryData.length === 0) {
      setSaveError("先に CSV を取り込んでください");
      return;
    }

    const ok = window.confirm(
      "コンディション説明の編集はお済みですか？\n\nOK で仕入データをサーバーDBに保存します。\n（保存先はサーバー側のDBです。運用PCの本番DBとは別です）"
    );
    if (!ok) return;

    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(null);

    try {
      const purchaseData = inventoryData.map(inventoryItemToPurchaseRecord);
      const result = await saveInventoryToDb(purchaseData, loadedRouteId);
      if (!result.ok || !result.data) {
        throw new Error(result.message ?? "DB保存に失敗しました");
      }
      setSaveSuccess(result.data.messages.join("\n"));
    } catch (error: unknown) {
      const message =
        error instanceof Error ? error.message : "DB保存中にエラーが発生しました";
      setSaveError(message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleExportCsv = async () => {
    setIsExporting(true);
    setExportError(null);
    setExportSuccess(null);

    try {
      const productsToExport = inventoryData.map((item) => ({
        jan: item.jan,
        productName: item.productName,
        quantity: item.quantity,
        plannedPrice: item.plannedPrice,
        purchasePrice: item.purchasePrice,
        breakEven: item.breakEven,
        condition: item.condition,
        sku: item.sku || "",
        asin: item.asin,
        conditionNote: item.conditionNote,
        priceTrace: item.priceTrace || 0,
      }));

      const response = await fetch(
        `${getApiBaseUrl()}/api/inventory/export-listing-csv`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer hirio-local-key",
          },
          body: JSON.stringify({ products: productsToExport }),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `CSVエクスポートに失敗しました: ${response.status} - ${errorText}`
        );
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "listing_export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setExportSuccess("CSVエクスポートが完了しました！");
    } catch (error: unknown) {
      const message =
        error instanceof Error
          ? error.message
          : "CSVエクスポート中にエラーが発生しました";
      setExportError(message);
    } finally {
      setIsExporting(false);
    }
  };

  const btnPrimary =
    "rounded-md bg-[var(--hirio-accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50";
  const btnDark =
    "rounded-md bg-[var(--hirio-ink)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50";
  const btnOutline =
    "rounded-md border border-[var(--hirio-line)] px-3 py-2 text-sm font-medium disabled:opacity-50";

  return (
    <div>
      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">ワークフロー</p>
        <p className="mt-1 text-xs text-[var(--hirio-muted)]">
          {WORKFLOW_STEPS.join(" → ")}
        </p>
        <p className="mt-2 text-xs text-[var(--hirio-muted)]">
          ⑤は上の「コンディション説明」タブ。⑦古物台帳生成はまだ未対応です。
        </p>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            <DummyInventoryCsvDownload />
            またはアマサーチの仕入 CSV を選ぶ
          </li>
          <li>ルートを選んで「ルートテンプレ読込」（店舗の IN/OUT が表示されます）</li>
          <li>「照合処理実行」で仕入れ先に店舗コードが入る</li>
          <li>「SKU生成」→ 必要ならコンディション説明 →「DB保存」→「出品CSV生成」</li>
        </ol>
      </section>

      <div className="space-y-6 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <CsvUploader onUploadSuccess={handleCsvUploadSuccess} />

        <section className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm">
          <p className="font-medium text-[var(--hirio-ink)]">② ルートテンプレ / ③ 照合</p>
          <p className="mt-1 text-xs text-[var(--hirio-muted)]">
            デスクトップの Excel 読込の代わりに、サーバー DB に保存済みのルートを読み込みます。
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-sm text-[var(--hirio-muted)]">
              ルート
              <select
                className="ml-2 max-w-xs rounded border border-[var(--hirio-line)] bg-white px-2 py-1 text-sm"
                value={selectedRouteId ?? ""}
                onChange={(e) => setSelectedRouteId(Number(e.target.value))}
                disabled={routes.length === 0 || isLoadingTemplate || isMatching}
              >
                {routes.length === 0 ? (
                  <option value="">ルートを読み込み中…</option>
                ) : (
                  routes.map((r) => (
                    <option key={r.id} value={r.id}>
                      {[r.route_date, r.route_display_name || r.route_code]
                        .filter(Boolean)
                        .join(" ")}
                    </option>
                  ))
                )}
              </select>
            </label>
            <label className="text-sm text-[var(--hirio-muted)]">
              許容（分）
              <input
                type="number"
                min={1}
                max={120}
                className="ml-2 w-16 rounded border border-[var(--hirio-line)] bg-white px-2 py-1 text-sm"
                value={timeTolerance}
                onChange={(e) => setTimeTolerance(Number(e.target.value) || 1)}
                disabled={isMatching}
              />
            </label>
            <button
              type="button"
              onClick={handleLoadRouteTemplate}
              disabled={isLoadingTemplate || selectedRouteId == null}
              className={btnDark}
            >
              {isLoadingTemplate ? "読込中…" : "ルートテンプレ読込"}
            </button>
            <button
              type="button"
              onClick={handleMatchStores}
              disabled={
                isMatching || selectedRouteId == null || inventoryData.length === 0
              }
              className={btnDark}
            >
              {isMatching ? "照合中…" : "照合処理実行"}
            </button>
          </div>
          {templateSuccess && (
            <p className="mt-2 whitespace-pre-wrap text-sm text-[var(--hirio-ok)]">
              {templateSuccess}
            </p>
          )}
          {templateError && (
            <p className="mt-2 text-sm text-[var(--hirio-danger)]">{templateError}</p>
          )}
          {matchSuccess && (
            <p className="mt-2 text-sm text-[var(--hirio-ok)]">{matchSuccess}</p>
          )}
          {matchError && (
            <p className="mt-2 text-sm text-[var(--hirio-danger)]">{matchError}</p>
          )}
        </section>

        {inventoryData.length > 0 && (
          <div>
            <div className="mb-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleGenerateSKU}
                disabled={isGeneratingSku}
                className={btnPrimary}
              >
                {isGeneratingSku ? "SKU生成中..." : "SKU生成"}
              </button>
              <button
                type="button"
                onClick={handleSaveToDb}
                disabled={isSaving}
                className={btnPrimary}
              >
                {isSaving ? "保存中..." : "DB保存"}
              </button>
              <button
                type="button"
                onClick={handleExportCsv}
                disabled={isExporting}
                className={btnOutline}
              >
                {isExporting ? "エクスポート中..." : "出品CSV生成"}
              </button>
            </div>
            <div className="mb-4 flex flex-col gap-2 text-sm">
              {skuSuccess && (
                <div className="rounded-md bg-[var(--hirio-accent-soft)] px-3 py-2 text-[var(--hirio-ok)]">
                  {skuSuccess}
                </div>
              )}
              {skuError && (
                <div className="rounded-md bg-red-50 px-3 py-2 text-[var(--hirio-danger)]">
                  エラー: {skuError}
                </div>
              )}
              {saveSuccess && (
                <div className="whitespace-pre-wrap rounded-md bg-[var(--hirio-accent-soft)] px-3 py-2 text-[var(--hirio-ok)]">
                  {saveSuccess}
                </div>
              )}
              {saveError && (
                <div className="rounded-md bg-red-50 px-3 py-2 text-[var(--hirio-danger)]">
                  エラー: {saveError}
                </div>
              )}
              {exportSuccess && (
                <div className="rounded-md bg-[var(--hirio-accent-soft)] px-3 py-2 text-[var(--hirio-ok)]">
                  {exportSuccess}
                </div>
              )}
              {exportError && (
                <div className="rounded-md bg-red-50 px-3 py-2 text-[var(--hirio-danger)]">
                  エラー: {exportError}
                </div>
              )}
            </div>
            <InventoryDataGrid
              data={inventoryData}
              onDataChange={handleInventoryDataChange}
            />
          </div>
        )}

        {templateSummary && (
          <section>
            <p className="mb-2 text-sm font-medium text-[var(--hirio-ink)]">
              ルート情報:{" "}
              {[
                templateSummary.route_date,
                templateSummary.route_display_name,
                templateSummary.departure_time
                  ? `出発 ${formatTimeShort(templateSummary.departure_time)}`
                  : null,
                templateSummary.return_time
                  ? `帰宅 ${formatTimeShort(templateSummary.return_time)}`
                  : null,
              ]
                .filter(Boolean)
                .join(" / ")}
            </p>
            {templateVisits.length === 0 ? (
              <p className="text-sm text-[var(--hirio-muted)]">訪問データがありません。</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-[var(--hirio-line)]">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-[var(--hirio-accent-soft)] text-[var(--hirio-muted)]">
                    <tr>
                      <th className="px-3 py-2">訪問順序</th>
                      <th className="px-3 py-2">店舗コード</th>
                      <th className="px-3 py-2">店舗名</th>
                      <th className="px-3 py-2">IN</th>
                      <th className="px-3 py-2">OUT</th>
                      <th className="px-3 py-2">滞在(分)</th>
                      <th className="px-3 py-2">想定粗利</th>
                      <th className="px-3 py-2">仕入点数</th>
                      <th className="px-3 py-2">メモ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {templateVisits.map((visit, index) => (
                      <tr
                        key={`${visit.store_code}-${index}`}
                        className="border-t border-[var(--hirio-line)]"
                      >
                        <td className="px-3 py-2">{visit.visit_order ?? index + 1}</td>
                        <td className="px-3 py-2">{visit.store_code || "—"}</td>
                        <td className="px-3 py-2">{visit.store_name || "—"}</td>
                        <td className="px-3 py-2">
                          {formatTimeShort(visit.store_in_time)}
                        </td>
                        <td className="px-3 py-2">
                          {formatTimeShort(visit.store_out_time)}
                        </td>
                        <td className="px-3 py-2">
                          {visit.stay_duration != null
                            ? Math.round(visit.stay_duration)
                            : "—"}
                        </td>
                        <td className="px-3 py-2">
                          {formatYen(visit.store_gross_profit)}
                        </td>
                        <td className="px-3 py-2">
                          {visit.store_item_count ?? "—"}
                        </td>
                        <td className="px-3 py-2">{visit.store_notes || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
