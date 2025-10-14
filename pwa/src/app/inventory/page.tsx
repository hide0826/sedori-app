'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import CsvUploader from '../components/CsvUploader';
import InventoryDataGrid from '../components/InventoryDataGrid';
import { InventoryItem } from '@/types/repricer';

const API_BASE_URL = 'http://localhost:8000'; // Define API base URL

export default function InventoryPage() {
  const [inventoryData, setInventoryData] = useState<InventoryItem[]>([]);
  const [isGeneratingSku, setIsGeneratingSku] = useState<boolean>(false);
  const [skuError, setSkuError] = useState<string | null>(null);
  const [skuSuccess, setSkuSuccess] = useState<string | null>(null);

  const handleCsvUploadSuccess = (data: InventoryItem[]) => {
    setInventoryData(data);
    setSkuError(null);
    setSkuSuccess(null);
  };

  const handleInventoryDataChange = (newData: InventoryItem[]) => {
    setInventoryData(newData);
    console.log("Inventory data updated:", newData);
  };

  const handleGenerateSKU = async () => {
    console.log('=== SKU生成開始 ===');
    setIsGeneratingSku(true);
    setSkuError(null);
    setSkuSuccess(null);
    console.log('ローディング状態: true');

    try {
      // キャメルケース → スネークケースに変換
      const requestData = {
        products: inventoryData.map(item => ({
          jan: item.jan,
          product_name: item.productName,
          purchase_price: item.purchasePrice,
          condition: item.condition
        }))
      };
      
      console.log('リクエストデータ:', requestData);
      console.log('API呼び出し開始...');

      const response = await fetch(`${API_BASE_URL}/api/inventory/generate-sku-bulk`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer hirio-local-key'
        },
        body: JSON.stringify(requestData)
      });

      console.log('APIレスポンス受信:', response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('API Error:', errorText);
        throw new Error(`API Error: ${response.status} - ${errorText}`);
      }

      console.log('JSONパース開始...');
      const result = await response.json();
      console.log('JSONパース完了:', result);

      if (!result.results || !Array.isArray(result.results)) {
        console.error('Unexpected response structure:', result);
        throw new Error('商品データが見つかりません');
      }

      console.log('データマッピング開始...');
      const updatedData = result.results.map((product: any) => ({
        jan: product.jan,
        productName: product.product_name,
        purchasePrice: product.purchase_price,
        condition: product.condition,
        sku: product.sku
      }));

      console.log('マッピング完了:', updatedData);
      console.log('状態更新開始...');
      
      setInventoryData(updatedData);
      setSkuSuccess('SKU生成が完了しました！');
      console.log('状態更新完了');
      console.log('成功メッセージ表示');
    } catch (error: any) {
      setSkuError(error.message || 'SKU生成中にエラーが発生しました');
      console.error('=== SKU生成エラー ===');
      console.error('エラー詳細:', error);
      console.error('エラーメッセージ:', error instanceof Error ? error.message : String(error));
      console.error('エラースタック:', error instanceof Error ? error.stack : 'なし');
    } finally {
      setIsGeneratingSku(false);
      console.log('ローディング状態: false');
      console.log('=== SKU生成処理終了 ===');
    }
  };


  return (
    <main className="flex min-h-screen flex-col items-center p-4 bg-gray-50">
      <div className="w-full max-w-4xl mb-8">
        <h1 className="text-3xl font-bold text-center text-gray-800">仕入管理システム</h1>
        <nav className="flex justify-center space-x-4 mt-4">
          <Link href="/" className="text-blue-600 hover:underline">
            価格改定
          </Link>
          <Link href="/inventory" className="text-blue-600 hover:underline">
            仕入管理
          </Link>
        </nav>
      </div>

      <div className="w-full max-w-4xl">
        <CsvUploader onUploadSuccess={handleCsvUploadSuccess} />

        {inventoryData.length > 0 && (
          <div className="mt-8">
            <div className="mb-4 flex flex-col sm:flex-row justify-between items-center">
              <button
                onClick={handleGenerateSKU}
                disabled={inventoryData.length === 0 || isGeneratingSku}
                className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded disabled:bg-blue-300 transition-colors duration-200"
              >
                {isGeneratingSku ? 'SKU生成中...' : 'SKU一括生成'}
              </button>
              {skuSuccess && (
                <div className="mt-2 sm:mt-0 p-2 bg-green-100 border border-green-400 text-green-700 rounded-md text-sm">
                  {skuSuccess}
                </div>
              )}
              {skuError && (
                <div className="mt-2 sm:mt-0 p-2 bg-red-100 border border-red-400 text-red-700 rounded-md text-sm">
                  エラー: {skuError}
                </div>
              )}
            </div>
            <InventoryDataGrid data={inventoryData} onDataChange={handleInventoryDataChange} />
          </div>
        )}
      </div>
    </main>
  );
}
