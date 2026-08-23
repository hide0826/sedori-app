"use client";

import { useEffect, useState } from "react";
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

const INNER_TABS = [
  { id: "conditions", label: "コンディション説明" },
  { id: "details", label: "詳細説明" },
] as const;

type InnerTabId = (typeof INNER_TABS)[number]["id"];

/**
 * デスクトップ「コンディション説明」の薄いPWA版。
 * 本番 hirio.db には繋がず、このブラウザの localStorage にだけ保存する。
 */
export function ConditionTemplatePanel() {
  const [inner, setInner] = useState<InnerTabId>("conditions");
  const [state, setState] = useState<ConditionTemplateState>(() =>
    createDefaultConditionTemplateState()
  );
  const [message, setMessage] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(loadConditionTemplateState());
    setHydrated(true);
  }, []);

  const flash = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(null), 2500);
  };

  const handleSave = () => {
    saveConditionTemplateState(state);
    flash("このブラウザに保存しました（本番DBとは未接続）");
  };

  const handleResetConditions = () => {
    if (!window.confirm("コンディション説明を初期のダミー文面に戻しますか？")) {
      return;
    }
    const defaults = createDefaultConditionTemplateState();
    setState((prev) => ({ ...prev, conditions: defaults.conditions }));
    flash("コンディション説明をリセットしました（まだ保存していません）");
  };

  const handleResetDetails = () => {
    if (!window.confirm("詳細説明を初期のダミー文面に戻しますか？")) {
      return;
    }
    const defaults = createDefaultConditionTemplateState();
    setState((prev) => ({
      ...prev,
      details: defaults.details,
      customLabels: defaults.customLabels,
    }));
    flash("詳細説明をリセットしました（まだ保存していません）");
  };

  if (!hydrated) {
    return (
      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-6 text-sm text-[var(--hirio-muted)]">
        読み込み中...
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">ダミー前提のコンディション説明</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>デスクトップのテンプレ編集画面に近い薄い版です</li>
          <li>
            保存先はこのPCのブラウザ（localStorage）だけです。本番の仕入DBとは
            まだつながっていません
          </li>
          <li>
            欠品を差し込みたい位置には{" "}
            <code className="rounded bg-[var(--hirio-surface)] px-1">
              {"{欠品}"}
            </code>{" "}
            と書いてください
          </li>
        </ul>
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
              各コンディションの出品コメント雛形です。編集後に「保存」を押してください。
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
                onClick={handleResetConditions}
                className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm"
              >
                リセット
              </button>
              <button
                type="button"
                onClick={handleSave}
                className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white"
              >
                保存
              </button>
            </div>
          </div>
        )}

        {inner === "details" && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--hirio-muted)]">
              欠品・詳細の定型文です。上段は名称固定、下段のカスタムは名称も変えられます。
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
                onClick={handleSave}
                className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white"
              >
                保存
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
