// pwa/src/types/repricer.ts
export interface RepriceRule {
  action: 'maintain' | 'priceTrace' | 'price_down_1' | 'price_down_2' | 'price_down_3' | 'price_down_4' | 'price_down_5' | 'price_down_ignore' | 'exclude';
  priceTrace: number | null;
}

export interface RepriceConfig {
  q4_rule_enabled?: boolean;
  reprice_rules: {
    [days: string]: RepriceRule;
  };
  updated_at: string;
}
