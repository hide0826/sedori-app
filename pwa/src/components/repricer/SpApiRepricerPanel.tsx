"use client";

import { useMemo, useState } from "react";
import ResultsDisplay from "@/app/components/ResultsDisplay";
import { getApiBaseUrl } from "@/lib/api-config";
import { ProcessingResult } from "@/types/repricer";
import {
  createDummyRepricerFile,
  DUMMY_LISTINGS,
  type DummyListingRow,
} from "@/components/repricer/dummyRepricerCsv";

const PIPELINE = [
  { step: 1, label: "①SP-API取得" },
  { step: 2, label: "②価格改定プレビュー" },
  { step: 3, label: "③価格確認（目視）" },
  { step: 4, label: "④価格改定実行" },
  { step: 5, label: "⑤Amazonへ価格反映" },
] as const;

type BusyAction = "fetch" | "preview" | "apply" | "patch" | null;

function normalizeProcessingResult(apiResponse: {
  summary: ProcessingResult["summary"];
  items?: Array<Record<string, unknown>>;
  updatedCsvContent?: string;
  updatedCsvEncoding?: string;
  reportCsvContent?: string;
}): ProcessingResult {
  const normalizeNumber = (v: unknown, fallback = 0): number => {
    if (v === null || v === undefined || v === "") return fallback;
    const n = typeof v === "number" ? v : Number(String(v).replace(/[,\s]/g, ""));
    return Number.isFinite(n) ? n : fallback;
  };

  const items = Array.isArray(apiResponse.items)
    ? apiResponse.items.map((it) => ({
        sku: String(it.sku ?? ""),
        productName:
          (it.productName as string | undefined) ??
          (it.title as string | undefined),
        days: normalizeNumber(it.days, 0),
        price: normalizeNumber(it.price, 0),
        new_price: normalizeNumber(it.new_price, 0),
        action: String(it.action ?? ""),
        priceTrace:
          it.priceTrace !== undefined
            ? normalizeNumber(it.priceTrace)
            : undefined,
        new_priceTrace:
          it.new_priceTrace !== undefined
            ? normalizeNumber(it.new_priceTrace)
            : undefined,
        reason: it.reason as string | undefined,
      }))
    : [];

  return {
    summary: apiResponse.summary,
    items,
    updatedCsvContent: apiResponse.updatedCsvContent,
    updatedCsvEncoding: apiResponse.updatedCsvEncoding,
    reportCsvContent: apiResponse.reportCsvContent,
  };
}

/**
 * デスクトップ「SP-API改定」の薄いPWA版。
 * Amazon SP-API への実送信はせず、ダミー取得＋既存 /repricer API で流れを試す。
 */
export function SpApiRepricerPanel() {
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [statusText, setStatusText] = useState("ワークフロー: 未実行");
  const [listings, setListings] = useState<DummyListingRow[]>([]);
  const [sourceLabel, setSourceLabel] = useState("");
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [hasExecuted, setHasExecuted] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [dryRunCount, setDryRunCount] = useState(1);
  const [patchLog, setPatchLog] = useState<string | null>(null);

  const canPreview = listings.length > 0 && busy === null;
  const canApply = result !== null && busy === null;
  const canPatch = hasExecuted && result !== null && busy === null;

  const changedCount = useMemo(() => {
    if (!result) return 0;
    return result.items.filter((it) => it.new_price !== it.price).length;
  }, [result]);

  const clearState = () => {
    setActiveStep(null);
    setStatusText("ワークフロー: 未実行");
    setListings([]);
    setSourceLabel("");
    setError(null);
    setResult(null);
    setHasExecuted(false);
    setPatchLog(null);
    setBusy(null);
  };

  const handleDummyFetch = async () => {
    setBusy("fetch");
    setError(null);
    setResult(null);
    setHasExecuted(false);
    setPatchLog(null);
    setActiveStep(1);
    setStatusText("ワークフロー: 実行中");
    // 実SP-APIの代わりに、少し待ってからダミー一覧を載せる
    await new Promise((r) => setTimeout(r, 400));
    setListings(DUMMY_LISTINGS);
    setSourceLabel("ダミー出品一覧（Amazon未接続）");
    setActiveStep(1);
    setStatusText("ワークフロー: 取得完了 → 次はプレビュー");
    setBusy(null);
  };

  const runRepricer = async (mode: "preview" | "apply") => {
    setBusy(mode === "preview" ? "preview" : "apply");
    setError(null);
    setPatchLog(null);
    setActiveStep(mode === "preview" ? 2 : 4);
    setStatusText("ワークフロー: 実行中");

    const formData = new FormData();
    formData.append("file", createDummyRepricerFile());
    const endpoint =
      mode === "preview"
        ? `${getApiBaseUrl()}/repricer/preview`
        : `${getApiBaseUrl()}/repricer/apply`;

    try {
      const res = await fetch(endpoint, { method: "POST", body: formData });
      const resBody = await res.text();
      if (!res.ok) {
        let detail = res.statusText;
        try {
          detail = JSON.parse(resBody).detail || detail;
        } catch {
          detail = resBody.substring(0, 200) || detail;
        }
        throw new Error(`APIエラー: ${res.status} - ${detail}`);
      }

      const apiResponse = JSON.parse(resBody);
      const normalized = normalizeProcessingResult(apiResponse);
      setResult(normalized);

      if (mode === "preview") {
        setActiveStep(3);
        setStatusText("ワークフロー: プレビュー完了 → 表を目視確認してください");
      } else {
        setHasExecuted(true);
        setActiveStep(4);
        setStatusText(
          "ワークフロー: 実行完了（ダミー）→ 必要なら Amazon 反映シミュレーションへ"
        );
      }
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "価格改定の呼び出しに失敗しました";
      setError(message);
      setStatusText("ワークフロー: エラー");
    } finally {
      setBusy(null);
    }
  };

  const handlePatchSimulation = async () => {
    if (!result) return;
    setBusy("patch");
    setError(null);
    setActiveStep(5);
    setStatusText("ワークフロー: 実行中");
    await new Promise((r) => setTimeout(r, 500));

    const targets = result.items.filter((it) => it.new_price !== it.price);
    const limit = dryRun ? Math.max(1, dryRunCount) : targets.length;
    const applied = targets.slice(0, limit);

    setPatchLog(
      [
        "Amazonへ価格反映はシミュレーションのみです（実送信なし）。",
        `変更候補: ${targets.length} 件`,
        dryRun
          ? `試験モード: 先頭 ${applied.length} 件を「送信したつもり」で記録`
          : `全 ${applied.length} 件を「送信したつもり」で記録`,
        ...applied.map(
          (it) =>
            `・${it.sku}: ${it.price} → ${it.new_price}（シミュ）`
        ),
      ].join("\n")
    );
    setActiveStep(5);
    setStatusText("ワークフロー: Amazon反映シミュレーション完了");
    setBusy(null);
  };

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">ダミー前提の SP-API改定</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            「SP-API取得」は Amazon に繋がず、固定のダミー出品を読み込みます
          </li>
          <li>
            プレビュー／実行は既存の改定API（サーバー上のダミー計算）を使います
          </li>
          <li>
            「Amazonへ価格反映」は画面上のシミュレーションのみ（本番送信なし）
          </li>
        </ul>
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <h2 className="text-lg font-semibold text-[var(--hirio-ink)]">
          SP-API操作・アクション
        </h2>

        <div className="mt-3 flex flex-wrap gap-1 text-xs text-[var(--hirio-muted)] md:text-sm">
          {PIPELINE.map((seg, i) => (
            <span key={seg.step} className="inline-flex items-center gap-1">
              {i > 0 && <span className="text-[var(--hirio-line)]">‐</span>}
              <span
                className={
                  activeStep === seg.step
                    ? "font-semibold text-[var(--hirio-accent)]"
                    : ""
                }
              >
                {seg.label}
              </span>
            </span>
          ))}
        </div>
        <p className="mt-2 text-sm text-[var(--hirio-muted)]">{statusText}</p>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <input
            type="text"
            readOnly
            value={sourceLabel}
            placeholder="①「SP-API取得（ダミー）」で出品一覧を読み込みます"
            className="min-w-0 flex-1 rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleDummyFetch}
            disabled={busy !== null}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "fetch" ? "取得中..." : "SP-API取得（ダミー）"}
          </button>
          <button
            type="button"
            onClick={() => runRepricer("preview")}
            disabled={!canPreview}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "preview" ? "計算中..." : "価格改定プレビュー"}
          </button>
          <button
            type="button"
            onClick={() => runRepricer("apply")}
            disabled={!canApply}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "apply" ? "実行中..." : "価格改定実行"}
          </button>
          <button
            type="button"
            onClick={handlePatchSimulation}
            disabled={!canPatch}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            title="実送信はしません。画面上のシミュレーションだけです"
          >
            {busy === "patch" ? "反映中..." : "Amazonへ価格反映"}
          </button>
          <button
            type="button"
            onClick={clearState}
            disabled={busy !== null}
            className="rounded-md border border-[var(--hirio-line)] px-4 py-2 text-sm disabled:opacity-50"
          >
            クリア
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-[var(--hirio-muted)]">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            試験: 先頭N件のみAmazon反映（シミュ）
          </label>
          <label className="inline-flex items-center gap-2">
            N=
            <input
              type="number"
              min={1}
              max={500}
              value={dryRunCount}
              onChange={(e) =>
                setDryRunCount(Math.max(1, Number(e.target.value) || 1))
              }
              className="w-20 rounded-md border border-[var(--hirio-line)] px-2 py-1"
            />
          </label>
          {result && (
            <span className="text-[var(--hirio-ink)]">
              価格変更候補: {changedCount} 件
            </span>
          )}
        </div>

        {error && (
          <div className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-[var(--hirio-danger)]">
            エラー: {error}
          </div>
        )}

        {listings.length > 0 && (
          <div className="mt-6 overflow-x-auto">
            <h3 className="mb-2 text-sm font-medium text-[var(--hirio-ink)]">
              取得一覧（ダミー）
            </h3>
            <table className="min-w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                  <th className="px-2 py-2 font-medium">SKU</th>
                  <th className="px-2 py-2 font-medium">ASIN</th>
                  <th className="px-2 py-2 font-medium">商品名</th>
                  <th className="px-2 py-2 text-right font-medium">price</th>
                  <th className="px-2 py-2 text-right font-medium">cost</th>
                  <th className="px-2 py-2 text-right font-medium">akaji</th>
                </tr>
              </thead>
              <tbody>
                {listings.map((row) => (
                  <tr
                    key={row.sku}
                    className="border-b border-[var(--hirio-line)]"
                  >
                    <td className="px-2 py-2 font-mono text-xs">{row.sku}</td>
                    <td className="px-2 py-2">{row.asin}</td>
                    <td className="max-w-xs truncate px-2 py-2">{row.title}</td>
                    <td className="px-2 py-2 text-right">{row.price}</td>
                    <td className="px-2 py-2 text-right">{row.cost}</td>
                    <td className="px-2 py-2 text-right">{row.akaji}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {result && <ResultsDisplay result={result} />}

        {patchLog && (
          <pre className="mt-4 whitespace-pre-wrap rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] p-3 text-xs text-[var(--hirio-ink)]">
            {patchLog}
          </pre>
        )}
      </div>

      <div className="rounded-lg border border-dashed border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <h2 className="text-lg font-semibold text-[var(--hirio-ink)]">
          最安追従（準備中）
        </h2>
        <p className="mt-2 text-sm text-[var(--hirio-muted)]">
          デスクトップの「同コンディション最安追従」に相当します。PWA
          ではまだダミーも載せていません。上段の ①〜⑤（3-6-9
          計算）とは別ロジックです。
        </p>
      </div>
    </div>
  );
}
