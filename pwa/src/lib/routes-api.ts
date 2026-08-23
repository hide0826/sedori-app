import { getApiBaseUrl } from "@/lib/api-config";

export type RouteDataSource = "server_db" | "dummy";

export type RouteSummary = {
  id: number;
  route_date: string | null;
  route_code: string | null;
  route_display_name: string;
  departure_time: string | null;
  return_time: string | null;
  store_count: number;
  total_item_count: number | null;
  total_gross_profit: number | null;
  estimated_hourly_rate: number | null;
  listing_completed: boolean;
  evidence_completed: boolean;
  images_completed: boolean;
  status_label: string;
  updated_at: string | null;
};

export type RouteVisit = {
  id: number | null;
  store_code: string | null;
  visit_order: number | null;
  store_in_time: string | null;
  store_out_time: string | null;
  stay_duration: number | null;
  store_item_count: number | null;
  store_gross_profit: number | null;
  store_notes: string | null;
  purchase_success: boolean | null;
};

export type RouteSummariesResponse = {
  source: RouteDataSource;
  db_path?: string;
  count: number;
  summaries: RouteSummary[];
};

export type RouteVisitsResponse = {
  source: RouteDataSource;
  db_path?: string;
  route_id: number;
  route_date: string | null;
  route_display_name: string | null;
  count: number;
  visits: RouteVisit[];
};

export function formatTimeShort(value: string | null | undefined): string {
  if (!value) return "—";
  const match = value.match(/(\d{1,2}:\d{2})/);
  if (match) return match[1];
  const d = new Date(value);
  if (!Number.isNaN(d.getTime())) {
    return d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  }
  return value;
}

export function formatYen(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `¥${Math.round(value).toLocaleString("ja-JP")}`;
}

export async function fetchRouteSummariesFromApi(): Promise<{
  ok: boolean;
  data?: RouteSummariesResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/routes/summaries?limit=50`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as RouteSummariesResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function fetchRouteVisitsFromApi(routeId: number): Promise<{
  ok: boolean;
  data?: RouteVisitsResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/routes/summaries/${routeId}/visits`;
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
