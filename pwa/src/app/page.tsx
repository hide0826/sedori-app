import Link from "next/link";
import { PageHeader } from "@/components/shell/PageHeader";
import { NAV_ITEMS } from "@/lib/nav";

export default function HomePage() {
  return (
    <div>
      <PageHeader
        title="TOP"
        description="HIRIO PWA の入り口です。いまは画面の枠（ガワ）を整える段階です。機能の本実装はデスクトップ側で続けます。"
      />

      <section className="mb-8 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] px-5 py-6">
        <p className="text-sm font-medium text-[var(--hirio-accent)]">Phase B</p>
        <h2 className="mt-1 text-xl font-semibold">サーバーでは殻だけ作る</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--hirio-muted)]">
          左のメニューから各画面へ移動できます。未実装の画面は「準備中」と表示されます。
          左下の API 状態は、FastAPI（通常は :8000）への接続確認です。
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-[var(--hirio-muted)]">メニュー一覧</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {NAV_ITEMS.filter((item) => item.href !== "/").map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] px-4 py-4 transition-colors hover:border-[var(--hirio-accent)] hover:bg-[var(--hirio-accent-soft)]"
            >
              <span className="font-medium">{item.label}</span>
              <span className="mt-1 block text-xs text-[var(--hirio-muted)]">{item.href}</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
