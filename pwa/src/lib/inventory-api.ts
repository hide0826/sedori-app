import { getApiBaseUrl } from "@/lib/api-config";
import type { InventoryItem } from "@/types/repricer";

export type MatchStoresResult = {
  status: string;
  stats: {
    total_rows: number;
    matched_rows: number;
  };
  data: Record<string, unknown>[];
};

export function inventoryItemToPurchaseRecord(
  item: InventoryItem
): Record<string, unknown> {
  return {
    仕入れ日: item.purchaseDate,
    コンディション: item.condition,
    ASIN: item.asin,
    JAN: item.jan,
    商品名: item.productName,
    仕入れ個数: item.quantity,
    仕入れ価格: item.purchasePrice,
    販売予定価格: item.plannedPrice,
    見込み利益: item.expectedProfit,
    損益分岐点: item.breakEven,
    コメント: item.comment,
    参考価格: item.referencePrice,
    発送方法: item.shippingMethod,
    仕入先: item.supplier,
    コンディション説明: item.conditionNote,
    SKU: item.sku,
    その他費用: item.otherCost,
    priceTrace: item.priceTrace,
  };
}

export function purchaseRecordToInventoryItem(
  record: Record<string, unknown>
): InventoryItem {
  const num = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  return {
    purchaseDate: String(record.仕入れ日 ?? record.purchaseDate ?? ""),
    condition: String(record.コンディション ?? record.condition ?? ""),
    asin: String(record.ASIN ?? record.asin ?? ""),
    jan: String(record.JAN ?? record.jan ?? ""),
    productName: String(record.商品名 ?? record.product_name ?? ""),
    quantity: num(record.仕入れ個数 ?? record.quantity),
    purchasePrice: num(record.仕入れ価格 ?? record.purchase_price),
    plannedPrice: num(record.販売予定価格 ?? record.planned_price),
    expectedProfit: num(record.見込み利益 ?? record.expected_profit),
    breakEven: num(record.損益分岐点 ?? record.break_even),
    comment: String(record.コメント ?? record.comment ?? ""),
    referencePrice: num(record.参考価格 ?? record.reference_price),
    shippingMethod: String(record.発送方法 ?? record.shipping_method ?? ""),
    supplier: String(
      record.仕入先 ?? record.仕入れ先 ?? record.supplier ?? ""
    ),
    conditionNote: String(
      record.コンディション説明 ?? record.condition_note ?? ""
    ),
    sku: String(record.SKU ?? record.sku ?? ""),
    otherCost: num(record.その他費用 ?? record.other_cost),
    priceTrace: num(record.priceTrace ?? record.price_trace),
  };
}

export async function matchStoresFromData(
  purchaseData: Record<string, unknown>[],
  routeSummaryId: number,
  timeToleranceMinutes = 1
): Promise<{ ok: boolean; data?: MatchStoresResult; message?: string }> {
  const url = `${getApiBaseUrl()}/api/inventory/match-stores-from-data`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        purchase_data: purchaseData,
        route_summary_id: routeSummaryId,
        time_tolerance_minutes: timeToleranceMinutes,
      }),
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 200)}` };
    }
    const data = (await res.json()) as MatchStoresResult;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export type RouteTemplateSummary = {
  id: number;
  route_date: string | null;
  route_code: string | null;
  route_display_name: string;
  departure_time: string | null;
  return_time: string | null;
};

export type RouteTemplateVisit = {
  id: number | null;
  visit_order: number | null;
  store_code: string;
  store_name: string;
  store_in_time: string | null;
  store_out_time: string | null;
  stay_duration: number | null;
  travel_time_from_prev: number | null;
  store_gross_profit: number | null;
  store_item_count: number | null;
  store_rating: number | null;
  store_notes: string | null;
};

export type RouteTemplateResult = {
  source: string;
  db_path?: string;
  summary: RouteTemplateSummary;
  count: number;
  visits: RouteTemplateVisit[];
};

export type SaveToDbResult = {
  status: string;
  purchase: {
    saved: boolean;
    message: string;
    stats?: {
      new_count: number;
      updated_count: number;
      skipped_count: number;
      total_count: number;
    };
    db_path?: string;
  };
  route: {
    saved: boolean;
    message: string;
    visit_count?: number;
  };
  messages: string[];
};

export async function fetchRouteTemplateFromApi(
  routeSummaryId: number
): Promise<{ ok: boolean; data?: RouteTemplateResult; message?: string }> {
  const url = `${getApiBaseUrl()}/api/inventory/route-template/${routeSummaryId}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 200)}` };
    }
    const data = (await res.json()) as RouteTemplateResult;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function saveInventoryToDb(
  purchaseData: Record<string, unknown>[],
  routeSummaryId: number | null
): Promise<{ ok: boolean; data?: SaveToDbResult; message?: string }> {
  const url = `${getApiBaseUrl()}/api/inventory/save-to-db`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        purchase_data: purchaseData,
        route_summary_id: routeSummaryId,
      }),
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 200)}` };
    }
    const data = (await res.json()) as SaveToDbResult;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}
