import { PageHeader } from "./PageHeader";

type ComingSoonProps = {
  title: string;
  description?: string;
};

export function ComingSoon({ title, description }: ComingSoonProps) {
  return (
    <div>
      <PageHeader
        title={title}
        description={description ?? "この画面は枠だけ用意しています。機能はデスクトップ側で更新します。"}
      />
      <div className="rounded-lg border border-dashed border-[var(--hirio-line)] bg-[var(--hirio-surface)] px-6 py-16 text-center">
        <p className="text-lg font-medium text-[var(--hirio-ink)]">準備中</p>
        <p className="mt-2 text-sm text-[var(--hirio-muted)]">
          Phase B ではメニュー枠と起動まわりだけ整えます。
        </p>
      </div>
    </div>
  );
}
