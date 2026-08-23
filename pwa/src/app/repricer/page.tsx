import { PageHeader } from "@/components/shell/PageHeader";
import RepricerSettingsTable from "@/app/components/RepricerSettingsTable";
import { DummyRepricerCsvDownload } from "@/components/repricer/DummyRepricerCsvDownload";

export default function RepricerPage() {
  return (
    <div>
      <PageHeader
        title="価格改定"
        description="ダミーCSVでプレビュー／適用の動作確認ができます。本番データは使いません。"
      />

      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">ダミーデータで試す手順</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-[var(--hirio-muted)]">
          <li>
            <DummyRepricerCsvDownload />
          </li>
          <li>下の「CSVファイルを選択」でそのファイルを選ぶ</li>
          <li>まず「プレビュー」で結果を確認（おすすめ）</li>
          <li>必要なら「適用」もダミー上だけで試せる</li>
        </ol>
        <p className="mt-2 text-xs text-[var(--hirio-muted)]">
          API は設定画面のベースURL（メインPCから開くときは通常{" "}
          <code className="rounded bg-white/70 px-1">http://192.168.0.200:8000</code>
          ）を使います。左下の接続状態も確認してください。
        </p>
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <RepricerSettingsTable />
      </div>
    </div>
  );
}
