import { getApiBaseUrl } from "@/lib/api-config";
import type { DbDataSource } from "@/lib/database-api";

export type ProductImageRow = {
  sku: string;
  product_name: string;
  jan: string;
  image_count: number;
  has_urls: boolean;
  status: string;
};

export type ScannedImageRow = {
  id: number | null;
  jan: string;
  file_name: string;
  file_path: string;
  capture_time: string | null;
  group_index: number | null;
  rotation: number;
};

export type ProductImagesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  registered_count: number;
  unregistered_count: number;
  items: ProductImageRow[];
};

export type ScannedImagesResponse = {
  source: DbDataSource;
  db_path?: string;
  count: number;
  total: number;
  items: ScannedImageRow[];
};

async function fetchJson<T>(url: string): Promise<{ ok: boolean; data?: T; message?: string }> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function fetchProductImagesFromApi(): Promise<{
  ok: boolean;
  data?: ProductImagesResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/images/products?limit=50`;
  return fetchJson<ProductImagesResponse>(url);
}

export async function fetchScannedImagesFromApi(): Promise<{
  ok: boolean;
  data?: ScannedImagesResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/images/scanned?limit=50`;
  return fetchJson<ScannedImagesResponse>(url);
}
