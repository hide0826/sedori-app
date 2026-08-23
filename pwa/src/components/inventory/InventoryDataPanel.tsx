"use client";

import React, { useState } from "react";
import CsvUploader from "@/app/components/CsvUploader";
import InventoryDataGrid from "@/app/components/InventoryDataGrid";
import { InventoryItem } from "@/types/repricer";
import { getApiBaseUrl } from "@/lib/api-config";
import { DummyInventoryCsvDownload } from "@/components/inventory/DummyInventoryCsvDownload";

/**
 * 仕入管理「仕入データ」サブタブの中身。
 * CSVアップロード → グリッド編集 → SKU生成 → 出品CSV出力。
 */
export function InventoryDataPanel() {
  const [inventoryData, setInventoryData] = useState<InventoryItem[]>([]);
  const [isGeneratingSku, setIsGeneratingSku] = useState(false);
  const [skuError, setSkuError] = useState<string | null>(null);
  const [skuSuccess, setSkuSuccess] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);

  const handleCsvUploadSuccess = (data: InventoryItem[]) => {
    setInventoryData(data);
    setSkuError(null);
    setSkuSuccess(null);
    setExportError(null);
    setExportSuccess(null);
  };

  const handleInventoryDataChange = (newData: InventoryItem[]) => {
    setInventoryData(newData);
  };

  const handleGenerateSKU = async () => {
    setIsGeneratingSku(true);
    setSkuError(null);
    setSkuSuccess(null);

    try {
      const requestData = {
        products: inventoryData.map((item) => ({
          jan: item.jan,
          product_name: item.productName,
          purchase_price: item.purchasePrice,
          condition: item.condition,
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

      const updatedData = result.results.map(
        (product: {
          jan: string;
          product_name: string;
          purchase_price: number;
          condition: string;
          sku: string;
        }) => ({
          jan: product.jan,
          productName: product.product_name,
          purchasePrice: product.purchase_price,
          condition: product.condition,
          sku: product.sku,
        })
      );

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

  return (
    <div>
      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">ダミーデータで試す手順</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            <DummyInventoryCsvDownload />
          </li>
          <li>下のアップロード欄でそのファイルを選ぶ</li>
          <li>プレビュー表が出たら必要ならセルを編集</li>
          <li>「SKU一括生成」→「出品CSVダウンロード」の順で試せる</li>
        </ol>
      </section>

      <div className="space-y-6 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <CsvUploader onUploadSuccess={handleCsvUploadSuccess} />

        {inventoryData.length > 0 && (
          <div>
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleGenerateSKU}
                  disabled={inventoryData.length === 0 || isGeneratingSku}
                  className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  {isGeneratingSku ? "SKU生成中..." : "SKU一括生成"}
                </button>
                {skuSuccess && (
                  <button
                    type="button"
                    onClick={handleExportCsv}
                    disabled={isExporting}
                    className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm font-medium disabled:opacity-50"
                  >
                    {isExporting
                      ? "エクスポート中..."
                      : "出品CSVダウンロード"}
                  </button>
                )}
              </div>
              <div className="flex flex-col gap-2 text-sm">
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
            </div>
            <InventoryDataGrid
              data={inventoryData}
              onDataChange={handleInventoryDataChange}
            />
          </div>
        )}
      </div>
    </div>
  );
}
