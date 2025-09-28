'use client';

import { useState, useEffect } from 'react';
import { RepriceConfig, RepriceRule, ProcessingResult } from '@/types/repricer';
import ResultsDisplay from './ResultsDisplay';

const API_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

// 定数を定義
const DAYS_INTERVALS = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360];
const ACTIONS = [
  { value: 'maintain', label: '維持' },
  { value: 'priceTrace', label: 'priceTrace設定' },
  { value: 'price_down_1', label: '1%値下げ' },
  { value: 'price_down_2', label: '2%値下げ' },
  { value: 'price_down_3', label: '3%値下げ' },
  { value: 'price_down_4', label: '4%値下げ' },
  { value: 'price_down_5', label: '5%値下げ' },
  { value: 'price_down_ignore', label: '利益無視値下げ' },
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
      const res = await fetch(`${API_URL}/repricer/config`);
      if (!res.ok) {
        throw new Error(`Failed to fetch config: ${res.statusText}`);
      }
      const data: RepriceConfig = await res.json();
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
      const res = await fetch(`${API_URL}/repricer/config`, {
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

  const handleRuleChange = (days: number, field: 'action' | 'value', value: any) => {
    setConfig((prevConfig) => {
      if (!prevConfig) return null;

      // Reactの状態の不変性を保証するため、ディープコピーを作成
      const newConfig = JSON.parse(JSON.stringify(prevConfig));
      const dayKey = days.toString();
      const ruleToUpdate = newConfig.reprice_rules[dayKey];

      if (ruleToUpdate) {
        ruleToUpdate[field] = value;

        // 「アクション」が変更された場合の連動ロジック
        if (field === 'action') {
          if (value !== 'priceTrace') {
            ruleToUpdate.value = 0; // priceTraceでないならvalueをリセット
          } else if (ruleToUpdate.value === 0 || ruleToUpdate.value === null) {
            ruleToUpdate.value = 1; // priceTraceに変更され、値が0ならデフォルトの1を設定
          }
        }
      }
      return newConfig;
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
      ? `${API_URL}/repricer/preview` 
      : `${API_URL}/repricer/test-upload`; // apply から test-upload に変更

    try {
      console.log(`[${mode.toUpperCase()}] Sending request to ${endpoint}`);
      const res = await fetch(endpoint, {
        method: 'POST',
        body: formData,
      });

      const resBody = await res.text();
      if (!res.ok) {
        let errorDetail = res.statusText;
        try {
            const errorJson = JSON.parse(resBody);
            errorDetail = errorJson.detail || errorDetail;
        } catch (e) {
            errorDetail = resBody.substring(0, 200) || errorDetail;
        }
        throw new Error(`APIエラー: ${res.status} - ${errorDetail}`);
      }
      
      const result: ProcessingResult = JSON.parse(resBody);
      console.log(`[${mode.toUpperCase()}] Received response:`, result);

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
            {Object.keys(config.reprice_rules)
              .map(Number)
              .sort((a, b) => a - b)
              .filter(days => config.reprice_rules[days.toString()])
              .map((days, index, sortedDays) => {
                const rule = config.reprice_rules[days.toString()];
                
                const formatDynamicDayLabel = (currentDays: number, currentIndex: number): string => {
                  if (currentIndex === 0) {
                    return `1-${currentDays}日`;
                  }
                  const prevDays = sortedDays[currentIndex - 1];
                  return `${prevDays + 1}-${currentDays}日`;
                };

                return (
                  <tr key={days} className="hover:bg-gray-50">
                    <td className="py-2 px-4 border-b text-center font-mono">{formatDynamicDayLabel(days, index)}</td>
                    <td className="py-2 px-4 border-b">
                      <select
                        value={rule.action}
                        onChange={(e) => handleRuleChange(days, 'action', e.target.value)}
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
                        onChange={(e) => handleRuleChange(days, 'value', parseInt(e.target.value))}
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