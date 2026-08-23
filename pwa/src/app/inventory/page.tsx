'use client';

import React, { useState } from 'react';
import CsvUploader from '../components/CsvUploader';
import InventoryDataGrid from '../components/InventoryDataGrid';
import { InventoryItem } from '@/types/repricer';
import { PageHeader } from '@/components/shell/PageHeader';
import { getApiBaseUrl } from '@/lib/api-config';

export default function InventoryPage() {
  const [inventoryData, setInventoryData] = useState<InventoryItem[]>([]);
  const [isGeneratingSku, setIsGeneratingSku] = useState<boolean>(false);
  const [skuError, setSkuError] = useState<string | null>(null);
  const [skuSuccess, setSkuSuccess] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);
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
        products: inventoryData.map(item => ({
          jan: item.jan,
          product_name: item.productName,
          purchase_price: item.purchasePrice,
          condition: item.condition
        }))
      };

      const response = await fetch(`${getApiBaseUrl()}/api/inventory/generate-sku-bulk`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer hirio-local-key'
        },
        body: JSON.stringify(requestData)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API Error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();

      if (!result.results || !Array.isArray(result.results)) {
        throw new Error('商品データが見つかりません');
      }

      const updatedData = result.results.map((product: {
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
        sku: product.sku
      }));

      setInventoryData(updatedData);
      setSkuSuccess('SKU生成が完了しました！');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'SKU生成中にエラーが発生しました';
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
      const productsToExport = inventoryData.map(item => ({
        jan: item.jan,
        productName: item.productName,
        quantity: item.quantity,
        plannedPrice: item.plannedPrice,
        purchasePrice: item.purchasePrice,
        breakEven: item.breakEven,
        condition: item.condition,
        sku: item.sku || '',
        asin: item.asin,
        conditionNote: item.conditionNote,
        priceTrace: item.priceTrace || 0
      }));

      const response = await fetch(`${getApiBaseUrl()}/api/inventory/export-listing-csv`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer hirio-local-key'
        },
        body: JSON.stringify({ products: productsToExport })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`CSVエクスポートに失敗しました: ${response.status} - ${errorText}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'listing_export.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setExportSuccess('CSVエクスポートが完了しました！');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'CSVエクスポート中にエラーが発生しました';
      setExportError(message);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="仕入管理"
        description="既存の CSV / SKU まわりを枠に入れています。本格更新はデスクトップ側で続けます。"
      />

      <div className="space-y-6 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <CsvUploader onUploadSuccess={handleCsvUploadSuccess} />

        {inventoryData.length > 0 && (
          <div>
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={handleGenerateSKU}
                  disabled={inventoryData.length === 0 || isGeneratingSku}
                  className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  {isGeneratingSku ? 'SKU生成中...' : 'SKU一括生成'}
                </button>
                {skuSuccess && (
                  <button
                    onClick={handleExportCsv}
                    disabled={isExporting}
                    className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm font-medium disabled:opacity-50"
                  >
                    {isExporting ? 'エクスポート中...' : '出品CSVダウンロード'}
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
            <InventoryDataGrid data={inventoryData} onDataChange={handleInventoryDataChange} />
          </div>
        )}
      </div>
    </div>
  );
}
