import { getApiBaseUrl } from "@/lib/api-config";
import type { DbDataSource } from "@/lib/database-api";
import { formatYen } from "@/lib/database-api";

export type ReceiptRow = {
  id: number | null;
  purchase_date: string | null;
  purchase_time: string;
  store_name: string;
  store_code: string;
  phone_number: string;
  registration_number: string;
  total_amount: number | null;
  discount_amount: number | null;
  price_difference: number | null;
  linked_skus: string;
  match_status: string;
  account_title: string;
  gcs_url: string;
  file_name: string;
  doc_type: string;
  sku: string;
  product_name: string;
  warranty_days: number | null;
  warranty_until: string;
};

export type ReceiptUpdatePayload = {
  account_title?: string;
  purchase_date?: string;
  purchase_time?: string;
  store_code?: string;
  store_name?: string;
  phone_number?: string;
  registration_number?: string;
  total_amount?: number | null;
  discount_amount?: number | null;
  linked_skus?: string;
  price_difference?: number | null;
};

export type ExpenseRow = {
  id: number | null;
  expense_date: string | null;
  expense_category: string;
  account_title: string;
  store_name: string;
  store_code: string;
  amount: number | null;
  quantity: number;
  unit_price: number | null;
  payment_method: string;
  receipt_id: number | null;
  receipt_file_path: string;
  memo: string;
};

export type ExpensePayload = {
  id?: number | null;
  expense_date: string;
  expense_category: string;
  account_title?: string;
  store_name?: string;
  store_code?: string;
  amount: number;
  quantity?: number;
  unit_price?: number | null;
  payment_method?: string;
  receipt_id?: number | null;
  receipt_file_path?: string;
  memo?: string;
};

export type AccountTitleRow = {
  id: number | null;
  name: string;
  sort_order: number;
  note: string;
  type: string;
};

export type CreditAccountRow = {
  id: number | null;
  name: string;
  raw_name: string;
  card_name: string;
  last_four_digits: string;
  is_default: boolean;
  sort_order: number;
  note: string;
  type: string;
};

export type JournalEntry = {
  id: number | null;
  transaction_date: string | null;
  debit_account: string;
  amount: number | null;
  credit_account: string;
  description: string;
  invoice_number: string;
  tax_category: string;
  image_url: string;
};

export type JournalPayload = {
  transaction_date: string;
  debit_account: string;
  amount: number;
  credit_account: string;
  description?: string;
  invoice_number?: string;
  tax_category?: string;
  image_url?: string;
};

export type ReceiptsResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  unmatched_count: number;
  receipts: ReceiptRow[];
};

export type ExpensesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  expenses: ExpenseRow[];
  categories?: string[];
  payment_methods?: string[];
};

export type DebitTitlesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  titles: AccountTitleRow[];
};

export type CreditAccountsResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  accounts: CreditAccountRow[];
};

export type JournalEntriesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  entries: JournalEntry[];
};

export const DEFAULT_EXPENSE_CATEGORIES = [
  "消耗品費",
  "旅費交通費",
  "通信費",
  "光熱費",
  "広告宣伝費",
  "その他",
];

export const DEFAULT_PAYMENT_METHODS = [
  "現金",
  "クレジットカード",
  "QR決済",
  "電子マネー",
  "その他",
];

async function fetchJson<T>(
  url: string,
  init?: RequestInit
): Promise<{ ok: boolean; data?: T; message?: string }> {
  try {
    const res = await fetch(url, { cache: "no-store", ...init });
    if (!res.ok) {
      const text = await res.text();
      let detail = text.slice(0, 160);
      try {
        detail = JSON.parse(text).detail || detail;
      } catch {
        /* keep */
      }
      return { ok: false, message: `HTTP ${res.status}: ${detail}` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

export async function fetchReceiptsFromApi(options?: {
  startDate?: string;
  endDate?: string;
}): Promise<{ ok: boolean; data?: ReceiptsResponse; message?: string }> {
  const params = new URLSearchParams({ limit: "100" });
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);
  return fetchJson(`${getApiBaseUrl()}/api/receipts?${params}`);
}

export async function updateReceiptOnApi(
  receiptId: number,
  payload: ReceiptUpdatePayload
): Promise<{ ok: boolean; data?: { receipt: ReceiptRow }; message?: string }> {
  return fetchJson(`${getApiBaseUrl()}/api/receipts/${receiptId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchExpensesFromApi(options?: {
  startDate?: string;
  endDate?: string;
}): Promise<{ ok: boolean; data?: ExpensesResponse; message?: string }> {
  const params = new URLSearchParams({ limit: "100" });
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);
  return fetchJson(`${getApiBaseUrl()}/api/expenses?${params}`);
}

export async function createExpenseOnApi(payload: ExpensePayload) {
  return fetchJson<{ expense: ExpenseRow }>(`${getApiBaseUrl()}/api/expenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateExpenseOnApi(expenseId: number, payload: ExpensePayload) {
  return fetchJson<{ expense: ExpenseRow }>(
    `${getApiBaseUrl()}/api/expenses/${expenseId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, id: expenseId }),
    }
  );
}

export async function deleteExpenseOnApi(expenseId: number) {
  return fetchJson(`${getApiBaseUrl()}/api/expenses/${expenseId}`, {
    method: "DELETE",
  });
}

export async function fetchDebitTitlesFromApi() {
  return fetchJson<DebitTitlesResponse>(`${getApiBaseUrl()}/api/account-titles/debit`);
}

export async function createDebitTitleOnApi(name: string, note = "") {
  return fetchJson<{ title: AccountTitleRow }>(
    `${getApiBaseUrl()}/api/account-titles/debit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, note }),
    }
  );
}

export async function deleteDebitTitleOnApi(titleId: number) {
  return fetchJson(`${getApiBaseUrl()}/api/account-titles/debit/${titleId}`, {
    method: "DELETE",
  });
}

export async function fetchCreditAccountsFromApi() {
  return fetchJson<CreditAccountsResponse>(
    `${getApiBaseUrl()}/api/account-titles/credit`
  );
}

export async function createCreditAccountOnApi(options: {
  name: string;
  card_name?: string;
  last_four_digits?: string;
  is_default?: boolean;
  note?: string;
}) {
  return fetchJson<{ account: CreditAccountRow }>(
    `${getApiBaseUrl()}/api/account-titles/credit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }
  );
}

export async function updateCreditAccountOnApi(
  accountId: number,
  options: {
    name?: string;
    card_name?: string;
    last_four_digits?: string;
    is_default?: boolean;
    note?: string;
  }
) {
  return fetchJson<{ account: CreditAccountRow }>(
    `${getApiBaseUrl()}/api/account-titles/credit/${accountId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }
  );
}

export async function deleteCreditAccountOnApi(accountId: number) {
  return fetchJson(`${getApiBaseUrl()}/api/account-titles/credit/${accountId}`, {
    method: "DELETE",
  });
}

export async function fetchJournalEntriesFromApi() {
  return fetchJson<JournalEntriesResponse>(
    `${getApiBaseUrl()}/api/journal/entries?limit=100`
  );
}

export async function createJournalEntryOnApi(payload: JournalPayload) {
  return fetchJson<{ entry: JournalEntry }>(
    `${getApiBaseUrl()}/api/journal/entries`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function updateJournalEntryOnApi(
  entryId: number,
  payload: JournalPayload
) {
  return fetchJson<{ entry: JournalEntry }>(
    `${getApiBaseUrl()}/api/journal/entries/${entryId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function deleteJournalEntryOnApi(entryId: number) {
  return fetchJson(`${getApiBaseUrl()}/api/journal/entries/${entryId}`, {
    method: "DELETE",
  });
}

export { formatYen };
