import { getApiBaseUrl } from "@/lib/api-config";

export type DbDataSource = "server_db" | "dummy";

export type StoreRow = {
  id: number | null;
  store_code: string;
  store_name: string;
  route_code: string;
  affiliated_route_name: string;
  address: string;
  phone: string;
  display_order: number | null;
  template_include: boolean;
};

export type ProductRow = {
  sku: string;
  jan: string;
  asin: string;
  product_name: string;
  purchase_date: string | null;
  purchase_price: number | null;
  quantity: number | null;
  store_code: string;
  store_name: string;
  listed_date: string | null;
};

export type StoresResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  stores: StoreRow[];
};

export type ProductsResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  products: ProductRow[];
};

export async function fetchStoresFromApi(q?: string): Promise<{
  ok: boolean;
  data?: StoresResponse;
  message?: string;
}> {
  const params = new URLSearchParams({ limit: "200" });
  if (q?.trim()) params.set("q", q.trim());
  const url = `${getApiBaseUrl()}/api/stores?${params.toString()}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as StoresResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function fetchProductsFromApi(): Promise<{
  ok: boolean;
  data?: ProductsResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/products?limit=50`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as ProductsResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export function formatYen(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `¥${Math.round(value).toLocaleString("ja-JP")}`;
}

export type RouteVisitRow = {
  route_date: string | null;
  route_code: string | null;
  route_name: string | null;
  store_code: string | null;
  store_name: string | null;
  store_in_time: string | null;
  store_out_time: string | null;
  stay_duration_minutes: number | null;
  store_item_count: number | null;
  store_gross_profit: number | null;
};

export type RouteVisitsResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  visits: RouteVisitRow[];
};

export async function fetchRouteVisitsFromApi(): Promise<{
  ok: boolean;
  data?: RouteVisitsResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/route-visits?limit=100`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as RouteVisitsResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}
