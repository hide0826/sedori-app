"use client";

import { useState } from "react";
import { SubTabs } from "@/components/shell/SubTabs";
import { ComingSoon } from "@/components/shell/ComingSoon";
import { InventoryDataPanel } from "@/components/inventory/InventoryDataPanel";

const INVENTORY_SUB_TABS = [
  { id: "data", label: "仕入データ" },
  { id: "condition", label: "コンディション説明" },
] as const;

type SubTabId = (typeof INVENTORY_SUB_TABS)[number]["id"];

/**
 * デスクトップの仕入管理と同じく、親メニュー内にサブタブを置く。
 * - 仕入データ: 既存の CSV / SKU / 出品CSV
 * - コンディション説明: 枠のみ（テンプレ編集はこれから）
 */
export function InventoryWorkspace() {
  const [active, setActive] = useState<SubTabId>("data");

  return (
    <div>
      <SubTabs
        tabs={INVENTORY_SUB_TABS}
        activeId={active}
        onChange={(id) => setActive(id as SubTabId)}
      />

      {active === "data" && <InventoryDataPanel />}

      {active === "condition" && (
        <ComingSoon
          title="コンディション説明"
          description="デスクトップの「コンディション説明」タブに相当する枠です。テンプレート編集・呼び出しはこれから載せます。"
        />
      )}
    </div>
  );
}
