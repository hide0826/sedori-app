"use client";

import { useCallback, useEffect, useState } from "react";
import { SubTabs } from "@/components/shell/SubTabs";
import {
  CONDITION_ROWS,
  CUSTOM_DEFAULT_LABELS,
  CUSTOM_KEYS,
  DETAIL_FIXED_ROWS,
  createDefaultConditionTemplateState,
  loadConditionTemplateState,
  saveConditionTemplateState,
  type ConditionTemplateState,
} from "@/components/inventory/conditionTemplates";
import {
  apiResponseToState,
  fetchConditionTemplatesFromApi,
  resetConditionTemplatesOnApi,
  saveConditionTemplatesToApi,
  type ConditionTemplateSource,
} from "@/lib/condition-templates-api";

const INNER_TABS = [
  { id: "conditions", label: "コンディション説明" },
  { id: "details", label: "詳細説明" },
] as const;

type InnerTabId = (typeof INNER_TABS)[number]["id"];

const SOURCE_LABEL: Record<ConditionTemplateSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  local_storage: "ブラウザ（localStorage）",
  default: "初期ダミー",
};

/**
 * コンディション説明テンプレ。
 * API（hirio.db）を優先し、失敗時は localStorage にフォールバックする。
 */
export function ConditionTemplatePanel() {
  const [inner, setInner] = useState<InnerTabId>("conditions");
  const [state, setState] = useState<ConditionTemplateState>(() =>
    createDefaultConditionTemplateState()
  );
  const [source, setSource] = useState<ConditionTemplateSource>("default");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const flash = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(null), 3000);
  };

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    const api = await fetchConditionTemplatesFromApi();
    if (api.ok && api.data) {
      setState(apiResponseToState(api.data));
      setSource("server_db");
      setDbPath(api.data.db_path ?? null);
      setLoading(false);
      setHydrated(true);
      return;
    }

    const local = loadConditionTemplateState();
    setState(local);
    setSource("local_storage");
    setDbPath(null);
    setLoading(false);
    setHydrated(true);
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const handleSave = async () => {
    setSaving(true);
    saveConditionTemplateState(state);

    const api = await saveConditionTemplatesToApi(state);
    if (api.ok) {
      setSource("server_db");
      flash("サーバーDBとブラウザの両方に保存しました");
    } else if (source === "server_db") {
      flash(
        `サーバー保存に失敗しました（${api.message ?? "不明"}）。ブラウザのみ保存済み`
      );
    } else {
      flash("ブラウザに保存しました（API未接続）");
    }
    setSaving(false);
  };

  const handleResetConditions = async () => {
    if (!window.confirm("コンディション説明を空欄にリセットしますか？")) {
      return;
    }

    if (source === "server_db") {
      const result = await resetConditionTemplatesOnApi();
      if (result.ok && result.data) {
        setState((prev) => ({
          ...prev,
          conditions: apiResponseToState(result.data!).conditions,
        }));
        flash("サーバーDBのコンディション説明をリセットしました");
        return;
      }
    }

    setState((prev) => ({
      ...prev,
      conditions: Object.fromEntries(
        CONDITION_ROWS.map((row) => [row.key, ""])
      ) as ConditionTemplateState["conditions"],
    }));
    flash("コンディション説明を空欄にリセットしました（未保存）");
  };

  const handleResetDetails = () => {
    if (!window.confirm("詳細説明を初期文面に戻しますか？")) {
      return;
    }
    const defaults = createDefaultConditionTemplateState();
    setState((prev) => ({
      ...prev,
      details: defaults.details,
      customLabels: defaults.customLabels,
    }));
    flash("詳細説明をリセットしました（保存ボタンで反映）");
  };

  if (!hydrated || loading) {
    return (
      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-6 text-sm text-[var(--hirio-muted)]">
        読み込み中...
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">コンディション説明テンプレ</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            読み込み元: <strong>{SOURCE_LABEL[source]}</strong>
            {dbPath && (
              <span className="ml-1 font-mono text-xs">({dbPath})</span>
            )}
          </li>
          <li>API 接続時は hirio.db に保存（デスクトップと同じDB）</li>
          <li>API 不通時はブラウザ（localStorage）にフォールバック</li>
          <li>
            欠品差し込み位置:{" "}
            <code className="rounded bg-[var(--hirio-surface)] px-1">
              {"{欠品}"}
            </code>
          </li>
        </ul>
        <button
          type="button"
          onClick={() => void loadTemplates()}
          className="mt-3 text-sm font-medium text-[var(--hirio-accent)] underline"
        >
          サーバーから再読み込み
        </button>
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={INNER_TABS}
          activeId={inner}
          onChange={(id) => setInner(id as InnerTabId)}
        />

        {message && (
          <div className="mb-4 rounded-md bg-[var(--hirio-accent-soft)] px-3 py-2 text-sm text-[var(--hirio-ok)]">
            {message}
          </div>
        )}

        {inner === "conditions" && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--hirio-muted)]">
              各コンディションの出品コメント雛形です。
            </p>
            <div className="space-y-3">
              {CONDITION_ROWS.map((row) => (
                <label key={row.key} className="block">
                  <span className="mb-1 block text-sm font-medium text-[var(--hirio-ink)]">
                    {row.name}
                  </span>
                  <textarea
                    value={state.conditions[row.key]}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        conditions: {
                          ...prev.conditions,
                          [row.key]: e.target.value,
                        },
                      }))
                    }
                    rows={3}
                    className="w-full rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-sm"
                  />
                </label>
              ))}
            </div>
            <div className="flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => void handleResetConditions()}
                className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm"
              >
                リセット
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        )}

        {inner === "details" && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--hirio-muted)]">
              欠品・詳細の定型文です。
            </p>
            <div className="space-y-3">
              {DETAIL_FIXED_ROWS.map((row) => (
                <label key={row.key} className="block">
                  <span className="mb-1 block text-sm font-medium text-[var(--hirio-ink)]">
                    {row.name}
                  </span>
                  <textarea
                    value={state.details[row.key]}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        details: {
                          ...prev.details,
                          [row.key]: e.target.value,
                        },
                      }))
                    }
                    rows={2}
                    className="w-full rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-sm"
                  />
                </label>
              ))}

              {CUSTOM_KEYS.map((ck) => (
                <div key={ck} className="grid gap-2 sm:grid-cols-[180px_1fr]">
                  <input
                    type="text"
                    value={state.customLabels[ck]}
                    placeholder={CUSTOM_DEFAULT_LABELS[ck]}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        customLabels: {
                          ...prev.customLabels,
                          [ck]: e.target.value,
                        },
                      }))
                    }
                    className="rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-center text-sm"
                  />
                  <textarea
                    value={state.details[ck]}
                    onChange={(e) =>
                      setState((prev) => ({
                        ...prev,
                        details: {
                          ...prev.details,
                          [ck]: e.target.value,
                        },
                      }))
                    }
                    rows={2}
                    className="w-full rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-sm"
                  />
                </div>
              ))}
            </div>
            <div className="flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={handleResetDetails}
                className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm"
              >
                リセット
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
