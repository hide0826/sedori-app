import { PageHeader } from "@/components/shell/PageHeader";
import RepricerSettingsTable from "@/app/components/RepricerSettingsTable";

export default function RepricerPage() {
  return (
    <div>
      <PageHeader
        title="価格改定"
        description="既存の PWA 画面を枠に入れています。本格的な機能更新はデスクトップ側で続けます。"
      />
      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <RepricerSettingsTable />
      </div>
    </div>
  );
}
