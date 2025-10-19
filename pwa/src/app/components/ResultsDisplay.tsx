'use client';

import { ProcessingResult } from '@/types/repricer';

interface ResultsDisplayProps {
  result: ProcessingResult;
}

export default function ResultsDisplay({ result }: ResultsDisplayProps) {
  const { summary, items, updatedCsvContent, reportCsvContent, updatedCsvEncoding } = result;
  // デバッグログ追加
  console.log('ResultsDisplay - First 3 items:', items.slice(0, 3));
  console.log('ResultsDisplay - First 3 SKU values:', items.slice(0, 3).map(item => item.sku));
  console.log('ResultsDisplay - Encoding:', updatedCsvEncoding);

  const handleDownload = (content: string, fileName: string, encoding?: string) => {
    let blob: Blob;

    // CP932 Base64 エンコーディングの場合
    if (encoding === 'cp932-base64') {
      console.log('Decoding CP932 Base64 content for:', fileName);
      try {
        // Base64 デコード
        const binaryString = atob(content);

        // CP932 バイナリに変換
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }

        // Blob 作成（CP932 バイナリとして保存）
        blob = new Blob([bytes], { type: 'text/csv' });
        console.log('Successfully decoded CP932 Base64, blob size:', blob.size);
      } catch (error) {
        console.error('Failed to decode Base64:', error);
        // フォールバック: 通常の文字列として保存
        blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
      }
    } else {
      // 通常の UTF-8 文字列
      blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
    }

    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="mt-8 pt-6 border-t-2 border-gray-200">
      <h2 className="text-xl font-bold mb-4">処理結果</h2>

      {/* サマリー */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="bg-gray-100 p-4 rounded-lg text-center">
          <div className="text-sm text-gray-600">処理対象</div>
          <div className="text-2xl font-bold">{summary.log_rows ?? 0}</div>
        </div>
        <div className="bg-green-100 p-4 rounded-lg text-center">
          <div className="text-sm text-green-600">更新</div>
          <div className="text-2xl font-bold text-green-800">{summary.updated_rows ?? 0}</div>
        </div>
        <div className="bg-red-100 p-4 rounded-lg text-center">
          <div className="text-sm text-red-600">対象外</div>
          <div className="text-2xl font-bold text-red-800">{summary.excluded_rows ?? 0}</div>
        </div>
        <div className="bg-yellow-100 p-4 rounded-lg text-center">
          <div className="text-sm text-yellow-600">Q4切替</div>
          <div className="text-2xl font-bold text-yellow-800">{summary.q4_switched ?? 0}</div>
        </div>
      </div>

      {/* ダウンロードボタン */}
      {updatedCsvContent && (
        <div className="my-6 flex justify-center space-x-4">
          <button
            onClick={() => handleDownload(updatedCsvContent, 'updated.csv', updatedCsvEncoding)}
            className="bg-purple-500 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded"
          >
            改定CSVダウンロード
          </button>
          {reportCsvContent && (
            <button
              onClick={() => handleDownload(reportCsvContent, 'report.csv')}
              className="bg-orange-500 hover:bg-orange-700 text-white font-bold py-2 px-4 rounded"
            >
              レポートCSVダウンロード
            </button>
          )}
        </div>
      )}

      {/* 結果テーブル */}
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-300">
          <thead className="bg-gray-100">
            <tr>
              <th className="py-2 px-3 border-b">SKU</th>
              <th className="py-2 px-3 border-b">出品日数</th>
              <th className="py-2 px-3 border-b">現在価格</th>
              <th className="py-2 px-3 border-b">改定後価格</th>
              <th className="py-2 px-3 border-b">アクション</th>
              <th className="py-2 px-3 border-b">Trace変更</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={item.sku} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="py-2 px-3 border-b text-xs font-mono">{item.sku}</td>
                <td className="py-2 px-3 border-b text-center">{item.days || 0}</td>
                <td className="py-2 px-3 border-b text-right">{item.price || 0}</td>
                <td className="py-2 px-3 border-b text-right font-bold">{item.new_price || 0}</td>
                <td className="py-2 px-3 border-b text-center">{item.action}</td>
                <td className="py-2 px-3 border-b text-center">
                  {item.priceTrace !== undefined && item.new_priceTrace !== undefined 
                    ? `${item.priceTrace} → ${item.new_priceTrace}` 
                    : item.priceTrace !== undefined 
                      ? item.priceTrace 
                      : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
