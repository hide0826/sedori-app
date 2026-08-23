'use client';

import { useState, useEffect } from 'react';
import { RepriceConfig, RepriceRule, ProcessingResult } from '@/types/repricer';
import ResultsDisplay from './ResultsDisplay';
import { getApiBaseUrl } from '@/lib/api-config';

// 定数を定義
const DAYS_INTERVALS = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360];
const ACTIONS = [
  { value: 'maintain', label: '維持' },
  { value: 'priceTrace', label: 'priceTrace設定' },
  { value: 'price_down_1', label: '1%値下げ' },
  { value: 'price_down_2', label: '2%値下げ' },
  { value: 'profit_ignore_down', label: '利益無視値下げ' },
  { value: 'exclude', label: '対象外' },
];
const PRICE_TRACE_OPTIONS = [
  { value: 0, label: '追従なし' },
  { value: 1, label: 'FBA最安値' },
  { value: 2, label: 'FBA最安値+マージン' },
  { value: 3, label: 'カート価格' },
  { value: 4, label: '在庫状況考慮' },
  { value: 5, label: 'プレミア価格' },
];

const formatDayLabel = (days: number, index: number): string => {
  if (index === 0) return `1-${days}日`;
  const prevDays = DAYS_INTERVALS[index - 1];
  return `${prevDays + 1}-${days}日`;
};


export default function RepricerSettingsTable() {
  const [config, setConfig] = useState<RepriceConfig | null>(null);
  const [q4RuleEnabled, setQ4RuleEnabled] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const [processingResult, setProcessingResult] = useState<ProcessingResult | null>(null);

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${getApiBaseUrl()}/repricer/config`);
      if (!res.ok) {
        throw new Error(`Failed to fetch config: ${res.statusText}`);
      }
      const response = await res.json();
      // API レスポンス形式に対応: {success: true, config: {...}}
      const data: RepriceConfig = response.success ? response.config : response;
      setConfig(data);
      setQ4RuleEnabled(data.q4_rule_enabled ?? true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    if (!config) return;
    setIsSaving(true);
    setError(null);
    const payload = { ...config, q4_rule_enabled: q4RuleEnabled };
    try {
      const res = await fetch(`${getApiBaseUrl()}/repricer/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`Failed to save config: ${res.statusText}`);
      alert('設定を保存しました。');
      fetchConfig();
    } catch (e: any) {
      setError(e.message);
      alert(`保存に失敗しました: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRuleChange = (days_from: number, field: 'action' | 'value', value: any) => {
    setConfig((prevConfig) => {
      if (!prevConfig) return null;
  
      const rules = Array.isArray(prevConfig.reprice_rules) ? prevConfig.reprice_rules : [];
      const newRules = rules.map(rule => {
        if (rule.days_from === days_from) {
          const updatedRule = { ...rule, [field]: value };
  
          // 連動ロジック
          if (field === 'action') {
            if (value !== 'priceTrace') {
              updatedRule.value = 0;
            } else if (updatedRule.value === 0 || updatedRule.value === null) {
              updatedRule.value = 1;
            }
          }
          return updatedRule;
        }
        return rule;
      });
  
      return { ...prevConfig, reprice_rules: newRules };
    });
  };
  
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (file.type !== 'text/csv') {
        alert('CSVファイルを選択してください。');
        event.target.value = '';
        setSelectedFile(null);
        return;
      }
      setSelectedFile(file);
      setProcessingResult(null); // 新しいファイル選択時に結果をクリア
      setProcessingMessage('');
      setError(null);
    }
  };

  const runProcessing = async (mode: 'preview' | 'apply') => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setProcessingResult(null);
    setError(null);
    const actionText = mode === 'preview' ? 'プレビュー' : '価格改定';
    setProcessingMessage(`${actionText}を実行中...`);
    console.log(`[${mode.toUpperCase()}] Starting processing for file: ${selectedFile.name}`);

    const formData = new FormData();
    formData.append('file', selectedFile);

    const endpoint = mode === 'preview'
      ? `${getApiBaseUrl()}/repricer/preview`
      : `${getApiBaseUrl()}/repricer/apply`;

    try {
      console.log(`[${mode.toUpperCase()}] Sending request to ${endpoint}`);
      const res = await fetch(endpoint, {
        method: 'POST',
        body: formData,
      });

      const resBody = await res.text();
      if (!res.ok) {
        let errorDetail = res.statusText;
        let userFriendlyMessage = '';

        try {
            const errorJson = JSON.parse(resBody);
            errorDetail = errorJson.detail || errorDetail;
        } catch (e) {
            errorDetail = resBody.substring(0, 200) || errorDetail;
        }

        // CSVフォーマットエラーの場合は分かりやすいメッセージに変換
        if (errorDetail.includes('Required columns missing') || errorDetail.includes('price')) {
          userFriendlyMessage = 'CSVファイルの形式が正しくありません。必要な列：SKU, price, akaji が含まれているか確認してください。';
        } else if (errorDetail.includes('CSV file is empty')) {
          userFriendlyMessage = 'CSVファイルが空です。データが含まれているか確認してください。';
        } else if (errorDetail.includes('Could not read or parse')) {
          userFriendlyMessage = 'CSVファイルの読み込みに失敗しました。ファイル形式を確認してください。';
        } else {
          userFriendlyMessage = `APIエラー: ${res.status} - ${errorDetail}`;
        }

        throw new Error(userFriendlyMessage);
      }
      
      const apiResponse = JSON.parse(resBody);
      console.log(`[${mode.toUpperCase()}] Received response:`, apiResponse);
      console.log("Full API response object:", apiResponse); // Log the entire result object
      
      // バックエンドAPIレスポンスをProcessingResult型に変換（型の正規化を実施）
      const normalizeNumber = (v: any, fallback = 0): number => {
        if (v === null || v === undefined || v === '') return fallback;
        const n = typeof v === 'number' ? v : Number(String(v).replace(/[,\s]/g, ''));
        return Number.isFinite(n) ? n : fallback;
      };

      const normalizedItems = Array.isArray(apiResponse.items) ? apiResponse.items.map((it: any) => ({
        sku: String(it.sku ?? ''),
        productName: it.productName ?? it.title ?? undefined,
        days: normalizeNumber(it.days, 0),
        price: normalizeNumber(it.price, 0),
        new_price: normalizeNumber(it.new_price, 0),
        action: String(it.action ?? ''),
        priceTrace: it.priceTrace !== undefined ? normalizeNumber(it.priceTrace, undefined as unknown as number) : undefined,
        new_priceTrace: it.new_priceTrace !== undefined ? normalizeNumber(it.new_priceTrace, undefined as unknown as number) : undefined,
        reason: it.reason ?? undefined,
      })) : [];

      const result: ProcessingResult = {
        summary: apiResponse.summary,
        items: normalizedItems,
        updatedCsvContent: apiResponse.updatedCsvContent,
        updatedCsvEncoding: apiResponse.updatedCsvEncoding,
        reportCsvContent: apiResponse.reportCsvContent
      };
      console.log('Result before ResultsDisplay:', result);
      console.log('First 3 SKU values from API:', apiResponse.items?.slice(0, 3).map((item: { sku?: string }) => item.sku));
      console.log('updatedCsvContent from API:', apiResponse.updatedCsvContent ? 'Present' : 'Missing');
      console.log('reportCsvContent from API:', apiResponse.reportCsvContent ? 'Present' : 'Missing');

      setProcessingResult(result);
      setProcessingMessage(`${actionText}が完了しました。`);

    } catch (e: any) {
      console.error(`[${mode.toUpperCase()}] Processing failed:`, e);
      setError(e.message);
      setProcessingMessage(`処理に失敗しました: ${e.message}`);
    }
    finally {
      setIsProcessing(false);
    }
  };

  const handlePreview = () => runProcessing('preview');
  const handleApply = () => runProcessing('apply');

  if (isLoading) return <div className="text-center p-8">読み込み中...</div>;
  if (error) return <div className="text-center p-8 text-red-500">エラー: {error}</div>;
  if (!config) return <div className="text-center p-8">設定データがありません。</div>;

  return (
    <div className="container mx-auto p-4">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">価格改定ルール設定</h1>
        <div className="flex items-center">
          <input
            type="checkbox"
            id="q4-rule"
            checked={q4RuleEnabled}
            onChange={(e) => setQ4RuleEnabled(e.target.checked)}
            className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
          />
          <label htmlFor="q4-rule" className="ml-2 block text-sm text-gray-900">
            Q4ルールを適用 (10月第1週)
          </label>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-300">
          <thead className="bg-gray-100">
            <tr>
              <th className="py-2 px-4 border-b">出品日数</th>
              <th className="py-2 px-4 border-b">アクション</th>
              <th className="py-2 px-4 border-b">priceTrace設定</th>
            </tr>
          </thead>
          <tbody>
            {(Array.isArray(config.reprice_rules) ? config.reprice_rules : [])
              .sort((a, b) => a.days_from - b.days_from)
              .map((rule) => {
                const getDaysRange = (daysFrom: number): string => {
                  const start = daysFrom - 29;
                  const end = daysFrom;
                  return `${start}-${end}日`;
                };

                return (
                  <tr key={rule.days_from} className="hover:bg-gray-50">
                    <td className="py-2 px-4 border-b text-center font-mono">{getDaysRange(rule.days_from)}</td>
                    <td className="py-2 px-4 border-b">
                      <select
                        value={rule.action}
                        onChange={(e) => handleRuleChange(rule.days_from, 'action', e.target.value)}
                        className="w-full p-2 border rounded"
                      >
                        {ACTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 px-4 border-b">
                      <select
                        value={rule.value ?? 0}
                        onChange={(e) => handleRuleChange(rule.days_from, 'value', parseInt(e.target.value))}
                        disabled={rule.action !== 'priceTrace'}
                        className="w-full p-2 border rounded disabled:bg-gray-200"
                      >
                        {PRICE_TRACE_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
      <div className="mt-6 flex justify-end space-x-4">
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded disabled:bg-gray-300"
        >
          {isSaving ? '保存中...' : '設定を保存'}
        </button>
      </div>

      {/* --- CSVファイル処理セクション --- */}
      <div className="mt-8 pt-6 border-t-2 border-gray-200">
        <h2 className="text-xl font-bold mb-4">CSVファイル処理</h2>

        {/* CSV要件の説明 */}
        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="text-sm font-semibold text-blue-800 mb-2">📋 Prister CSVファイル形式対応</h3>
          <p className="text-sm text-blue-700 mb-2">PristerエクスポートCSVファイル（16列形式）に対応しています：</p>
          <div className="text-sm text-blue-700 mb-2">
            <strong>必須列:</strong> SKU, price, akaji
          </div>
          <details className="text-sm text-blue-700">
            <summary className="cursor-pointer font-semibold mb-1">📄 全対応列一覧（クリックで展開）</summary>
            <ul className="list-disc ml-5 space-y-1 mt-2">
              <li><strong>SKU</strong>: 商品識別子（日付形式: 2025_09_20_商品名）</li>
              <li><strong>ASIN</strong>: Amazon商品識別子</li>
              <li><strong>title</strong>: 商品タイトル</li>
              <li><strong>number</strong>: 数量</li>
              <li><strong>price</strong>: 現在価格（改定対象）</li>
              <li><strong>cost</strong>: 仕入れ価格</li>
              <li><strong>akaji</strong>: 赤字価格（利益ガード用）</li>
              <li><strong>takane</strong>: 高値設定</li>
              <li><strong>condition</strong>: 商品状態</li>
              <li><strong>conditionNote</strong>: 状態説明</li>
              <li><strong>priceTrace</strong>: priceTrace設定（改定対象）</li>
              <li><strong>leadtime</strong>: リードタイム</li>
              <li><strong>amazon-fee</strong>: Amazon手数料</li>
              <li><strong>shipping-price</strong>: 送料</li>
              <li><strong>profit</strong>: 利益</li>
              <li><strong>add-delete</strong>: 追加/削除フラグ</li>
            </ul>
            <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs">
              <strong>注意:</strong> Excel数式記法（="値"）で保存されたCSVファイルも自動対応します
            </div>
          </details>
        </div>

        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center bg-gray-50">
          <input
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            className="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-full file:border-0
              file:text-sm file:font-semibold
              file:bg-blue-50 file:text-blue-700
              hover:file:bg-blue-100"
          />
          {selectedFile && (
            <div className="mt-4 text-sm text-gray-600">
              選択中: <strong>{selectedFile.name}</strong> ({(selectedFile.size / 1024).toFixed(2)} KB)
            </div>
          )}
        </div>

        {(isProcessing || processingMessage) && (
          <div className={`mt-4 p-3 rounded text-center ${isProcessing ? 'bg-yellow-100 border border-yellow-400 text-yellow-700' : 'bg-green-100 border border-green-400 text-green-700'}`}>
            {processingMessage}
          </div>
        )}

        <div className="mt-6 flex justify-center space-x-4">
          <button
            onClick={handlePreview}
            disabled={!selectedFile || isProcessing}
            className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-6 rounded disabled:bg-blue-300"
          >
            プレビュー実行
          </button>
          <button
            onClick={handleApply}
            disabled={!selectedFile || isProcessing}
            className="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-6 rounded disabled:bg-green-300"
          >
            価格改定実行
          </button>
        </div>
      </div>

      {/* --- 結果表示セクション --- */}
      {processingResult && <ResultsDisplay result={processingResult} />}
    </div>
  );
}
