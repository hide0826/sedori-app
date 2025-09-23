'use client';

import { useState, useEffect } from 'react';
import { RepriceConfig, RepriceRule } from '@/types/repricer';

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

// 日数表記をフォーマットするヘルパー関数
const formatDayLabel = (days: number, index: number): string => {
  if (index === 0) {
    return `1-${days}日`;
  }
  const prevDays = DAYS_INTERVALS[index - 1];
  return `${prevDays + 1}-${days}日`;
};

export default function RepricerSettingsTable() {
  const [config, setConfig] = useState<RepriceConfig | null>(null);
  const [q4RuleEnabled, setQ4RuleEnabled] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

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
    
    const payload = {
      ...config,
      q4_rule_enabled: q4RuleEnabled,
    };

    try {
      const res = await fetch(`${API_URL}/repricer/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error(`Failed to save config: ${res.statusText}`);
      }
      alert('設定を保存しました。');
      fetchConfig(); // 保存後に再取得して同期
    } catch (e: any) {
      setError(e.message);
      alert(`保存に失敗しました: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRuleChange = (days: number, field: keyof RepriceRule, value: any) => {
    if (!config) return;

    const newRules = { ...config.reprice_rules };
    const currentRule = newRules[days.toString()];

    if (currentRule) {
      (currentRule[field] as any) = value;

      if (field === 'action' && value !== 'priceTrace') {
        currentRule.priceTrace = 0;
      }
    }
    
    setConfig({ ...config, reprice_rules: newRules });
  };


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
            id="q-rule"
            checked={q4RuleEnabled}
            onChange={(e) => setQ4RuleEnabled(e.target.checked)}
            className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
          />
          <label htmlFor="q-rule" className="ml-2 block text-sm text-gray-900">
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
            {DAYS_INTERVALS.map((days, index) => {
              const rule = config.reprice_rules[days.toString()];
              if (!rule) return null;

              return (
                <tr key={days} className="hover:bg-gray-50">
                  <td className="py-2 px-4 border-b text-center font-mono">{formatDayLabel(days, index)}</td>
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
                      value={rule.priceTrace ?? 0}
                      onChange={(e) => handleRuleChange(days, 'priceTrace', parseInt(e.target.value))}
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
          className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded disabled:bg-blue-300"
        >
          {isSaving ? '保存中...' : '設定を保存'}
        </button>
      </div>
    </div>
  );
}