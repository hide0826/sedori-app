import { getApiBaseUrl } from "@/lib/api-config";

export type SpApiHealthResponse = {
  status: string;
  service: string;
  credentials_configured: boolean;
  has_seller_id?: boolean;
  source?: string;
  error?: string;
};

export type SpApiListingRow = {
  sku: string;
  asin: string;
  title: string;
  price: number | null;
  cost: number | null;
  akaji: number | null;
};

export type FetchListingsResponse = {
  source: string;
  count: number;
  listings: SpApiListingRow[];
  csv_content: string;
  csv_filename: string;
};

export type FollowRepriceItem = {
  sku: string;
  days: number | null;
  currentPrice: number | null;
  competitorMin: number | null;
  newPrice: number | null;
  rule: string;
};

export type FollowRepriceResponse = {
  source: string;
  count: number;
  items: FollowRepriceItem[];
  changed_count: number;
  patch?: Record<string, unknown>;
};

export type PatchPricesResponse = {
  source: string;
  dry_run: boolean;
  target_count?: number;
  targets?: Array<Record<string, unknown>>;
  success_count?: number;
  failed_count?: number;
};

async function fetchJson<T>(
  url: string,
  init?: RequestInit
): Promise<{ ok: boolean; data?: T; message?: string }> {
  try {
    const res = await fetch(url, { cache: "no-store", ...init });
    if (!res.ok) {
      const text = await res.text();
      let detail = text.slice(0, 200);
      try {
        detail = JSON.parse(text).detail || detail;
      } catch {
        /* keep text */
      }
      return { ok: false, message: `HTTP ${res.status}: ${detail}` };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function fetchSpApiHealth(): Promise<{
  ok: boolean;
  data?: SpApiHealthResponse;
  message?: string;
}> {
  return fetchJson<SpApiHealthResponse>(`${getApiBaseUrl()}/api/sp-api/health`);
}

export async function fetchListingsFromSpApi(): Promise<{
  ok: boolean;
  data?: FetchListingsResponse;
  message?: string;
}> {
  return fetchJson<FetchListingsResponse>(`${getApiBaseUrl()}/api/sp-api/fetch-listings`, {
    method: "POST",
  });
}

export async function runFollowRepriceFromSpApi(options: {
  listings: SpApiListingRow[];
  maxListings: number;
  applyAmazon: boolean;
}): Promise<{ ok: boolean; data?: FollowRepriceResponse; message?: string }> {
  return fetchJson<FollowRepriceResponse>(`${getApiBaseUrl()}/api/sp-api/follow-reprice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      listings: options.listings,
      max_listings: options.maxListings,
      apply_amazon: options.applyAmazon,
    }),
  });
}

export async function patchPricesViaSpApi(options: {
  items: Array<Record<string, unknown>>;
  dryRun: boolean;
  maxItems: number;
}): Promise<{ ok: boolean; data?: PatchPricesResponse; message?: string }> {
  return fetchJson<PatchPricesResponse>(`${getApiBaseUrl()}/api/sp-api/patch-prices`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items: options.items,
      dry_run: options.dryRun,
      max_items: options.maxItems,
    }),
  });
}

export function createRepricerFileFromCsv(content: string, filename: string): File {
  return new File([content], filename, { type: "text/csv" });
}
