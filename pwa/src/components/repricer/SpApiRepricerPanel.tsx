"use client";

import { useEffect, useMemo, useState } from "react";
import ResultsDisplay from "@/app/components/ResultsDisplay";
import { getApiBaseUrl } from "@/lib/api-config";
import { ProcessingResult } from "@/types/repricer";
import {
  createDummyRepricerFile,
  DUMMY_LISTINGS,
  type DummyListingRow,
} from "@/components/repricer/dummyRepricerCsv";
import {
  createRepricerFileFromCsv,
  fetchListingsFromSpApi,
  fetchSpApiHealth,
  patchPricesViaSpApi,
  runFollowRepriceFromSpApi,
  type SpApiListingRow,
} from "@/lib/sp-api";

const PIPELINE = [
  { step: 1, label: "①SP-API取得" },
  { step: 2, label: "②価格改定プレビュー" },
  { step: 3, label: "③価格確認（目視）" },
  { step: 4, label: "④価格改定実行" },
  { step: 5, label: "⑤Amazonへ価格反映" },
] as const;

type BusyAction = "fetch" | "preview" | "apply" | "patch" | "follow" | null;

type FollowResultRow = {
  sku: string;
  days: number;
  currentPrice: number;
  competitorMin: number;
  newPrice: number;
  rule: string;
};

const DUMMY_FOLLOW_RESULTS: FollowResultRow[] = [
  {
    sku: "20250201-B0007RBX52-UM-1650-1",
    days: 90,
    currentPrice: 4463,
    competitorMin: 4200,
    newPrice: 4200,
    rule: "150日未満 → 最安揃え",
  },
  {
    sku: "20250201-B000LVNOKQ-UVG-330-1",
    days: 210,
    currentPrice: 1120,
    competitorMin: 980,
    newPrice: 1020,
    rule: "150日以降 → ライバル−100円（TP下限）",
  },
  {
    sku: "20250201-B000RGMGAY-UVG-550-1",
    days: 180,
    currentPrice: 2971,
    competitorMin: 3100,
    newPrice: 2971,
    rule: "変更なし（最安より高い／TP維持）",
  },
];

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
 * デスクトップ「SP-API改定」の PWA 版。
 * SP-API 認証があれば本番取得・反映。なければダミーにフォールバック。
 */
export function SpApiRepricerPanel() {
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [statusText, setStatusText] = useState("ワークフロー: 未実行");
  const [listings, setListings] = useState<DummyListingRow[]>([]);
  const [sourceLabel, setSourceLabel] = useState("");
  const [dataSource, setDataSource] = useState<"sp_api" | "dummy">("dummy");
  const [csvContent, setCsvContent] = useState<string | null>(null);
  const [csvFilename, setCsvFilename] = useState<string>("test_repricer_dummy.csv");
  const [spApiReady, setSpApiReady] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [hasExecuted, setHasExecuted] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [dryRunCount, setDryRunCount] = useState(1);
  const [patchLog, setPatchLog] = useState<string | null>(null);
  const [followBusy, setFollowBusy] = useState(false);
  const [followResults, setFollowResults] = useState<FollowResultRow[] | null>(
    null
  );
  const [followLog, setFollowLog] = useState<string | null>(null);
  const [followHours, setFollowHours] = useState(8);
  const [followMax, setFollowMax] = useState(400);
  const [followPatch, setFollowPatch] = useState(false);
  const [followAuto, setFollowAuto] = useState(false);

  useEffect(() => {
    void fetchSpApiHealth().then((res) => {
      setSpApiReady(res.ok && Boolean(res.data?.credentials_configured));
    });
  }, []);

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
    setDataSource("dummy");
    setCsvContent(null);
    setCsvFilename("test_repricer_dummy.csv");
    setError(null);
    setResult(null);
    setHasExecuted(false);
    setPatchLog(null);
    setFollowResults(null);
    setFollowLog(null);
    setBusy(null);
  };

  const toListingRows = (rows: SpApiListingRow[]): DummyListingRow[] =>
    rows.map((row) => ({
      sku: row.sku,
      asin: row.asin,
      title: row.title,
      price: row.price ?? 0,
      cost: row.cost ?? 0,
      akaji: row.akaji ?? 0,
    }));

  const handleFollow = async () => {
    setFollowBusy(true);
    setFollowLog(null);
    setFollowResults(null);

    if (dataSource === "sp_api" && listings.length > 0) {
      const res = await runFollowRepriceFromSpApi({
        listings: listings.map((r) => ({
          sku: r.sku,
          asin: r.asin,
          title: r.title,
          price: r.price,
          cost: r.cost,
          akaji: r.akaji,
        })),
        maxListings: followMax,
        applyAmazon: followPatch,
      });
      if (res.ok && res.data) {
        setFollowResults(
          res.data.items.map((it) => ({
            sku: it.sku,
            days: it.days ?? 0,
            currentPrice: it.currentPrice ?? 0,
            competitorMin: it.competitorMin ?? 0,
            newPrice: it.newPrice ?? 0,
            rule: it.rule,
          }))
        );
        const lines = [
          followPatch
            ? "最安追従 → Amazon PATCH 実行（本番）"
            : "最安追従（計算のみ）",
          `調査: ${res.data.count} 件 / 変更候補: ${res.data.changed_count} 件`,
        ];
        if (res.data.patch && typeof res.data.patch === "object") {
          const p = res.data.patch as Record<string, unknown>;
          if (p.success_count != null) {
            lines.push(`PATCH 成功: ${p.success_count} / 失敗: ${p.failed_count ?? 0}`);
          }
        }
        setFollowLog(lines.join("\n"));
        setFollowBusy(false);
        return;
      }
      setFollowLog(res.message ?? "最安追従 API に失敗しました");
      setFollowBusy(false);
      return;
    }

    await new Promise((r) => setTimeout(r, 600));

    const limit = Math.min(followMax, DUMMY_FOLLOW_RESULTS.length);
    const rows = DUMMY_FOLLOW_RESULTS.slice(0, limit);
    setFollowResults(rows);

    const changed = rows.filter((r) => r.newPrice !== r.currentPrice);
    const lines = [
      "最安追従はダミー計算のみです（SP-API Offers 未接続）。",
      `調査上限: ${followMax} 件 → 今回 ${rows.length} 件`,
      `価格変更候補: ${changed.length} 件`,
    ];
    if (followPatch) {
      lines.push(
        ...changed.map(
          (r) => `・${r.sku}: ${r.currentPrice} → ${r.newPrice}（反映シミュ）`
        )
      );
    } else {
      lines.push("「巡回後にAmazonへ反映」は OFF のため計算のみ");
    }
    setFollowLog(lines.join("\n"));
    setFollowBusy(false);
  };

  const handleFetch = async () => {
    setBusy("fetch");
    setError(null);
    setResult(null);
    setHasExecuted(false);
    setPatchLog(null);
    setActiveStep(1);
    setStatusText("ワークフロー: 実行中");

    if (spApiReady) {
      setStatusText("ワークフロー: SP-API レポート取得中（数分かかる場合あり）…");
      const res = await fetchListingsFromSpApi();
      if (res.ok && res.data) {
        setListings(toListingRows(res.data.listings));
        setCsvContent(res.data.csv_content);
        setCsvFilename(res.data.csv_filename);
        setDataSource("sp_api");
        setSourceLabel(`SP-API 出品一覧（${res.data.count} 件）`);
        setActiveStep(1);
        setStatusText("ワークフロー: 取得完了 → 次はプレビュー");
        setBusy(null);
        return;
      }
      setError(res.message ?? "SP-API 取得に失敗しました。ダミーに切り替えます。");
    }

    await new Promise((r) => setTimeout(r, 400));
    setListings(DUMMY_LISTINGS);
    setCsvContent(null);
    setDataSource("dummy");
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
    const file =
      csvContent && dataSource === "sp_api"
        ? createRepricerFileFromCsv(csvContent, csvFilename)
        : createDummyRepricerFile();
    formData.append("file", file);
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

  const handlePatch = async () => {
    if (!result) return;
    setBusy("patch");
    setError(null);
    setActiveStep(5);
    setStatusText("ワークフロー: 実行中");

    const targets = result.items.filter((it) => it.new_price !== it.price);
    const limit = dryRun ? Math.max(1, dryRunCount) : targets.length;
    const applied = targets.slice(0, limit);

    if (dataSource === "sp_api" && spApiReady) {
      const res = await patchPricesViaSpApi({
        items: applied.map((it) => ({
          sku: it.sku,
          price: it.price,
          new_price: it.new_price,
          productName: it.productName,
        })),
        dryRun: dryRun,
        maxItems: limit,
      });
      if (res.ok && res.data) {
        if (res.data.dry_run) {
          setPatchLog(
            [
              "Amazon PATCH（試験モード: 件数確認のみ）",
              `変更候補: ${targets.length} 件 → 試行 ${res.data.target_count ?? limit} 件`,
            ].join("\n")
          );
        } else {
          setPatchLog(
            [
              "Amazon PATCH 実行完了（本番）",
              `成功: ${res.data.success_count ?? 0} / 失敗: ${res.data.failed_count ?? 0}`,
            ].join("\n")
          );
        }
        setActiveStep(5);
        setStatusText("ワークフロー: Amazon反映完了");
        setBusy(null);
        return;
      }
      setError(res.message ?? "Amazon PATCH に失敗しました");
      setBusy(null);
      return;
    }

    await new Promise((r) => setTimeout(r, 500));

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
        <p className="font-medium">
          SP-API改定
          {spApiReady === null
            ? "（接続確認中…）"
            : spApiReady
              ? " — 認証OK（本番取得可）"
              : " — ダミーモード（認証未設定）"}
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            「SP-API取得」は認証があれば Amazon 出品レポートを取得（数分かかる場合あり）
          </li>
          <li>
            プレビュー／実行はサーバー上の改定API（取得CSVまたはダミーCSV）
          </li>
          <li>
            「Amazonへ価格反映」は試験モードOFF＋SP-API接続時のみ本番 PATCH
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
            placeholder="①「SP-API取得」で出品一覧を読み込みます"
            className="min-w-0 flex-1 rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleFetch}
            disabled={busy !== null}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "fetch"
              ? spApiReady
                ? "SP-API取得中..."
                : "取得中..."
              : spApiReady
                ? "SP-API取得"
                : "SP-API取得（ダミー）"}
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
            onClick={handlePatch}
            disabled={!canPatch}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            title={
              dataSource === "sp_api" && !dryRun
                ? "Amazon へ本番 PATCH します"
                : "試験モードまたはダミー時はシミュレーション"
            }
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
              取得一覧（{dataSource === "sp_api" ? "SP-API" : "ダミー"}）
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

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <h2 className="text-lg font-semibold text-[var(--hirio-ink)]">
          最安追従（SP-API・3-6-9とは別）
        </h2>
        <p className="mt-2 text-sm text-[var(--hirio-muted)]">
          150日未満は同コンディション最安に揃え、以降は TP
          へ寄せつつライバルより100円安くするロジックのダミー版です。
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleFollow}
            disabled={followBusy}
            className="rounded-md bg-[var(--hirio-accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {followBusy ? "計算中..." : "最安追従を実行（ダミー）"}
          </button>
          <label className="inline-flex items-center gap-2 text-sm text-[var(--hirio-muted)]">
            <input
              type="checkbox"
              checked={followAuto}
              onChange={(e) => setFollowAuto(e.target.checked)}
              disabled
            />
            自動巡回（PWA未対応・表示のみ）
          </label>
          <label className="inline-flex items-center gap-2 text-sm">
            間隔(時間)
            <input
              type="number"
              min={4}
              max={12}
              value={followHours}
              onChange={(e) => setFollowHours(Number(e.target.value) || 8)}
              className="w-16 rounded-md border border-[var(--hirio-line)] px-2 py-1"
            />
          </label>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={followPatch}
              onChange={(e) => setFollowPatch(e.target.checked)}
            />
            巡回後にAmazonへ反映（シミュ）
          </label>
          <label className="inline-flex items-center gap-2 text-sm">
            上限件数
            <input
              type="number"
              min={1}
              max={5000}
              value={followMax}
              onChange={(e) => setFollowMax(Number(e.target.value) || 400)}
              className="w-20 rounded-md border border-[var(--hirio-line)] px-2 py-1"
            />
          </label>
        </div>

        {followResults && (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                  <th className="px-2 py-2 font-medium">SKU</th>
                  <th className="px-2 py-2 text-right font-medium">出品日数</th>
                  <th className="px-2 py-2 text-right font-medium">現在</th>
                  <th className="px-2 py-2 text-right font-medium">同条件最安</th>
                  <th className="px-2 py-2 text-right font-medium">改定後</th>
                  <th className="px-2 py-2 font-medium">ルール</th>
                </tr>
              </thead>
              <tbody>
                {followResults.map((row) => (
                  <tr
                    key={row.sku}
                    className="border-b border-[var(--hirio-line)]"
                  >
                    <td className="px-2 py-2 font-mono text-xs">{row.sku}</td>
                    <td className="px-2 py-2 text-right">{row.days}</td>
                    <td className="px-2 py-2 text-right">{row.currentPrice}</td>
                    <td className="px-2 py-2 text-right">
                      {row.competitorMin}
                    </td>
                    <td className="px-2 py-2 text-right font-medium">
                      {row.newPrice}
                    </td>
                    <td className="px-2 py-2 text-xs">{row.rule}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {followLog && (
          <pre className="mt-4 whitespace-pre-wrap rounded-md border border-[var(--hirio-line)] bg-[var(--hirio-bg)] p-3 text-xs text-[var(--hirio-ink)]">
            {followLog}
          </pre>
        )}
      </div>
    </div>
  );
}
