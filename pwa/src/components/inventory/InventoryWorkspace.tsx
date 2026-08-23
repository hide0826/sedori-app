"use client";

import { useState } from "react";
import { SubTabs } from "@/components/shell/SubTabs";
import { InventoryDataPanel } from "@/components/inventory/InventoryDataPanel";
import { ConditionTemplatePanel } from "@/components/inventory/ConditionTemplatePanel";

const INVENTORY_SUB_TABS = [
  { id: "data", label: "仕入データ" },
  { id: "condition", label: "コンディション説明" },
] as const;

type SubTabId = (typeof INVENTORY_SUB_TABS)[number]["id"];

/**
 * デスクトップの仕入管理と同じく、親メニュー内にサブタブを置く。
 * - 仕入データ: 既存の CSV / SKU / 出品CSV
 * - コンディション説明: テンプレ編集の薄い版（ブラウザ保存）
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

      {active === "condition" && <ConditionTemplatePanel />}
    </div>
  );
}
