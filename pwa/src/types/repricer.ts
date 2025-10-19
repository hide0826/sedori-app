// pwa/src/types/repricer.ts

// Inventory item interface for CSV upload
export interface InventoryItem {
  purchaseDate: string;
  condition: string;
  asin: string;
  jan: string;
  productName: string;
  quantity: number;
  purchasePrice: number;
  plannedPrice: number;
  expectedProfit: number;
  breakEven: number;
  comment: string;
  referencePrice: number;
  shippingMethod: string;
  supplier: string;
  conditionNote: string;
  sku: string;
  otherCost: number;
  priceTrace: number;
}

export interface RepriceRule {
  days_from: number;
  action: 'maintain' | 'priceTrace' | 'price_down_1' | 'price_down_2' | 'price_down_3' | 'price_down_4' | 'price_down_5' | 'price_down_ignore' | 'exclude';
  value: number | null;
}

export interface RepriceConfig {
  q4_rule_enabled?: boolean;
  reprice_rules: RepriceRule[] | { [days: string]: RepriceRule };
  updated_at: string;
}

// Part 2: 結果表示用
export interface ResultItem {
  sku: string;
  productName?: string;
  days: number; // バックエンドAPIレスポンスのキー名に合わせる
  price: number; // バックエンドAPIレスポンスのキー名に合わせる
  new_price: number; // バックエンドAPIレスポンスのキー名に合わせる
  action: string;
  priceTrace?: number; // バックエンドAPIレスポンスのキー名に合わせる
  new_priceTrace?: number; // バックエンドAPIレスポンスのキー名に合わせる
  reason?: string; // バックエンドAPIレスポンスのキー名に合わせる
}

export interface ProcessingResult {
  summary: {
    updated_rows: number;
    excluded_rows: number;
    q4_switched: number;
    date_unknown: number;
    log_rows: number;
  };
  items: ResultItem[];
  updatedCsvContent?: string;
  updatedCsvEncoding?: string; // "cp932-base64" などのエンコーディング情報
  reportCsvContent?: string;
}
