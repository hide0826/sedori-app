'use client';

import { ProcessingResult } from '@/types/repricer';

interface ResultsDisplayProps {
  result: ProcessingResult;
}

export default function ResultsDisplay({ result }: ResultsDisplayProps) {
  const { summary, items, updatedCsvContent, reportCsvContent } = result;
  // デバッグログ追加
  console.log('ResultsDisplay - First 3 items:', items.slice(0, 3));

  const handleDownload = (content: string, fileName: string) => {
    const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
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
          <div className="text-2xl font-bold">{summary.total}</div>
        </div>
        <div className="bg-green-100 p-4 rounded-lg text-center">
          <div className="text-sm text-green-600">更新</div>
          <div className="text-2xl font-bold text-green-800">{summary.updated}</div>
        </div>
        <div className="bg-red-100 p-4 rounded-lg text-center">
          <div className="text-sm text-red-600">対象外</div>
          <div className="text-2xl font-bold text-red-800">{summary.excluded}</div>
        </div>
        <div className="bg-blue-100 p-4 rounded-lg text-center col-span-2 md:col-span-2">
            <div className="text-sm text-blue-600 mb-1">アクション別件数</div>
            <div className="text-xs text-blue-800 flex flex-wrap justify-center gap-x-2">
                {Object.entries(summary.actionCounts).map(([action, count]) => (
                    <span key={action} className="font-mono">{action}: {count}</span>
                ))}
            </div>
        </div>
      </div>

      {/* ダウンロードボタン */}
      <div className="my-6 flex justify-center space-x-4">
        <button
          onClick={() => handleDownload(updatedCsvContent, 'updated.csv')}
          className="bg-purple-500 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded"
        >
          改定CSVダウンロード
        </button>
        <button
          onClick={() => handleDownload(reportCsvContent, 'report.csv')}
          className="bg-orange-500 hover:bg-orange-700 text-white font-bold py-2 px-4 rounded"
        >
          レポートCSVダウンロード
        </button>
      </div>

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
                <td className="py-2 px-3 border-b text-center">{item.daysSinceListed}</td>
                <td className="py-2 px-3 border-b text-right">{item.currentPrice || 0}</td>
                <td className="py-2 px-3 border-b text-right font-bold">{item.newPrice || 0}</td>
                <td className="py-2 px-3 border-b text-center">{item.action}</td>
                <td className="py-2 px-3 border-b text-center">{item.priceTraceChange ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
