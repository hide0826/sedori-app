"use client";

import { PageHeader } from "@/components/shell/PageHeader";
import { InventoryWorkspace } from "@/components/inventory/InventoryWorkspace";

export default function InventoryPage() {
  return (
    <div>
      <PageHeader
        title="仕入管理"
        description="デスクトップと同じく、仕入データとコンディション説明をサブタブで分けています。本格更新はデスクトップ側が正です。"
      />
      <InventoryWorkspace />
    </div>
  );
}
