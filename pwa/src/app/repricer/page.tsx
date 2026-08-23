import { PageHeader } from "@/components/shell/PageHeader";
import { RepricerWorkspace } from "@/components/repricer/RepricerWorkspace";

export default function RepricerPage() {
  return (
    <div>
      <PageHeader
        title="価格改定"
        description="デスクトップと同じく、改定実行・改定ルール・SP-API改定のサブタブに分けています。まずはダミーCSVで確認できます。"
      />
      <RepricerWorkspace />
    </div>
  );
}
