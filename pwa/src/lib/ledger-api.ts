import { getApiBaseUrl } from "@/lib/api-config";
import type { DbDataSource } from "@/lib/database-api";
import { formatYen } from "@/lib/database-api";

export type LedgerEntry = {
  id: number | null;
  entry_date: string | null;
  hinmei: string;
  feature: string;
  counterparty_name: string;
  amount: number | null;
  qty: number | null;
  sku: string;
};

export type LedgerEntriesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  entries: LedgerEntry[];
};

export async function fetchLedgerEntriesFromApi(): Promise<{
  ok: boolean;
  data?: LedgerEntriesResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/ledger/entries?limit=50`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as LedgerEntriesResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export { formatYen };
