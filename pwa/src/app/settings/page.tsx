"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import {
  checkApiHealth,
  getApiBaseUrl,
  getDefaultApiBaseUrl,
  setApiBaseUrl,
} from "@/lib/api-config";

export default function SettingsPage() {
  const [apiUrl, setApiUrl] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [testOk, setTestOk] = useState<boolean | null>(null);

  useEffect(() => {
    setApiUrl(getApiBaseUrl());
  }, []);

  const handleSave = (event: FormEvent) => {
    event.preventDefault();
    setApiBaseUrl(apiUrl);
    setSavedMessage("保存しました");
    setTestMessage(null);
    setTestOk(null);
    window.dispatchEvent(new Event("hirio-api-config-changed"));
  };

  const handleTest = async () => {
    const result = await checkApiHealth(apiUrl.trim() || getDefaultApiBaseUrl());
    setTestOk(result.ok);
    setTestMessage(result.ok ? "接続できました" : `接続できません: ${result.message}`);
  };

  const handleReset = () => {
    const fallback = getDefaultApiBaseUrl();
    setApiUrl(fallback);
    setApiBaseUrl(fallback);
    setSavedMessage("初期値に戻しました");
    window.dispatchEvent(new Event("hirio-api-config-changed"));
  };

  return (
    <div>
      <PageHeader
        title="設定"
        description="PWA 殻向けの最小設定です。API の接続先だけをここで覚えます。"
      />

      <form
        onSubmit={handleSave}
        className="max-w-xl space-y-4 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-5"
      >
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">API ベースURL</span>
          <input
            type="url"
            value={apiUrl}
            onChange={(event) => setApiUrl(event.target.value)}
            placeholder="http://localhost:8000"
            className="w-full rounded-md border border-[var(--hirio-line)] px-3 py-2 text-sm outline-none focus:border-[var(--hirio-accent)]"
          />
          <span className="mt-1.5 block text-xs text-[var(--hirio-muted)]">
            サーバー本体: http://localhost:8000 ／ メインPCから: http://192.168.0.200:8000
            （未保存なら、開いているホスト名の :8000 を自動使用）
          </span>
        </label>

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white"
          >
            保存
          </button>
          <button
            type="button"
            onClick={handleTest}
            className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm"
          >
            接続テスト
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm"
          >
            初期値に戻す
          </button>
        </div>

        {savedMessage && (
          <p className="text-sm text-[var(--hirio-ok)]">{savedMessage}</p>
        )}
        {testMessage && (
          <p
            className={`text-sm ${
              testOk ? "text-[var(--hirio-ok)]" : "text-[var(--hirio-danger)]"
            }`}
          >
            {testMessage}
          </p>
        )}
      </form>
    </div>
  );
}
