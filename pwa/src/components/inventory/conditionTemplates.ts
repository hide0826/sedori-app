/** コンディション説明テンプレ（PWAダミー用。本番DBとは未接続） */

export const CONDITION_ROWS = [
  { key: "new", name: "新品" },
  { key: "like_new", name: "中古(ほぼ新品)" },
  { key: "very_good", name: "中古(非常に良い)" },
  { key: "good", name: "中古(良い)" },
  { key: "acceptable", name: "中古(可)" },
] as const;

export const DETAIL_FIXED_ROWS = [
  { key: "取説欠品", name: "取説欠品" },
  { key: "内箱欠品", name: "内箱欠品" },
  { key: "取説・内箱欠品", name: "取説・内箱欠品" },
] as const;

export const CUSTOM_KEYS = ["custom1", "custom2", "custom3"] as const;

export const CUSTOM_DEFAULT_LABELS: Record<(typeof CUSTOM_KEYS)[number], string> =
  {
    custom1: "カスタム1",
    custom2: "カスタム2",
    custom3: "カスタム3",
  };

export type ConditionKey = (typeof CONDITION_ROWS)[number]["key"];
export type DetailKey =
  | (typeof DETAIL_FIXED_ROWS)[number]["key"]
  | (typeof CUSTOM_KEYS)[number];

export type ConditionTemplateState = {
  conditions: Record<ConditionKey, string>;
  details: Record<DetailKey, string>;
  customLabels: Record<(typeof CUSTOM_KEYS)[number], string>;
};

const STORAGE_KEY = "hirio.pwa.conditionTemplates.v1";

/** 初回用のダミー文面（サーバー検証用） */
export function createDefaultConditionTemplateState(): ConditionTemplateState {
  return {
    conditions: {
      new: "【新品】未開封・未使用です。{欠品}",
      like_new: "【ほぼ新品】使用感はほとんどありません。{欠品}",
      very_good:
        "【非常に良い】目立つ傷や汚れはありません。動作確認済みです。{欠品}",
      good: "【良い】使用感はありますが、動作に問題はありません。{欠品}",
      acceptable:
        "【可】傷・汚れがあります。動作確認済みです。詳細は写真をご確認ください。{欠品}",
    },
    details: {
      取説欠品:
        "取扱説明書が欠品しています。メーカーサイトにてダウンロード可能です。",
      内箱欠品: "内箱なし",
      "取説・内箱欠品": "取扱説明書および内箱が欠品しています。",
      custom1: "",
      custom2: "",
      custom3: "",
    },
    customLabels: { ...CUSTOM_DEFAULT_LABELS },
  };
}

export function loadConditionTemplateState(): ConditionTemplateState {
  const fallback = createDefaultConditionTemplateState();
  if (typeof window === "undefined") return fallback;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ConditionTemplateState>;
    return {
      conditions: { ...fallback.conditions, ...(parsed.conditions || {}) },
      details: { ...fallback.details, ...(parsed.details || {}) },
      customLabels: {
        ...fallback.customLabels,
        ...(parsed.customLabels || {}),
      },
    };
  } catch {
    return fallback;
  }
}

export function saveConditionTemplateState(state: ConditionTemplateState): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}
