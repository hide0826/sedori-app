import { getApiBaseUrl } from "@/lib/api-config";
import type { DbDataSource } from "@/lib/database-api";
import { formatYen } from "@/lib/database-api";

export type AnalysisMetric = {
  metric: string;
  value: number;
  note: string;
};

export type AnalysisSummaryResponse = {
  source: DbDataSource;
  db_path?: string;
  days: number;
  store_count: number;
  metrics: AnalysisMetric[];
};

export type StoreScoreRow = {
  store_code: string;
  store_name: string;
  score: number;
  hourly_estimate: number;
  visit_count: number;
  total_gross_profit: number;
  trend: string;
};

export type StoreScoresResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  stores: StoreScoreRow[];
};

export async function fetchAnalysisSummaryFromApi(): Promise<{
  ok: boolean;
  data?: AnalysisSummaryResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/analysis/summary?days=30`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as AnalysisSummaryResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function fetchStoreScoresFromApi(): Promise<{
  ok: boolean;
  data?: StoreScoresResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/analysis/store-scores?limit=30`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as StoreScoresResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export function formatMetricValue(metric: string, value: number): string {
  if (metric.includes("総額") || metric.includes("単価")) {
    return formatYen(value);
  }
  return value.toLocaleString("ja-JP");
}

export { formatYen };
