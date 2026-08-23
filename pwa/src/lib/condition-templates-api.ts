import { getApiBaseUrl } from "@/lib/api-config";
import {
  CONDITION_ROWS,
  CUSTOM_DEFAULT_LABELS,
  CUSTOM_KEYS,
  DETAIL_FIXED_ROWS,
  createDefaultConditionTemplateState,
  type ConditionKey,
  type ConditionTemplateState,
  type DetailKey,
} from "@/components/inventory/conditionTemplates";

export type ConditionTemplateSource = "server_db" | "local_storage" | "default";

export type ConditionTemplateApiResponse = {
  source: ConditionTemplateSource;
  db_path?: string;
  conditions: Array<{ key: string; name: string; description: string }>;
  details: {
    keywords: Record<string, string>;
    custom_labels: Record<string, string>;
  };
};

export function apiResponseToState(
  data: ConditionTemplateApiResponse
): ConditionTemplateState {
  const defaults = createDefaultConditionTemplateState();
  const conditions = { ...defaults.conditions };
  for (const item of data.conditions) {
    if (item.key in conditions) {
      conditions[item.key as ConditionKey] = item.description ?? "";
    }
  }

  const details = { ...defaults.details };
  for (const row of DETAIL_FIXED_ROWS) {
    if (data.details.keywords[row.key] !== undefined) {
      details[row.key as DetailKey] = data.details.keywords[row.key];
    }
  }
  for (const ck of CUSTOM_KEYS) {
    if (data.details.keywords[ck] !== undefined) {
      details[ck] = data.details.keywords[ck];
    }
  }

  const customLabels = { ...defaults.customLabels };
  for (const ck of CUSTOM_KEYS) {
    if (data.details.custom_labels[ck]) {
      customLabels[ck] = data.details.custom_labels[ck];
    }
  }

  return { conditions, details, customLabels };
}

export function stateToApiPayload(state: ConditionTemplateState) {
  return {
    conditions: CONDITION_ROWS.map((row) => ({
      key: row.key,
      name: row.name,
      description: state.conditions[row.key],
    })),
    details: {
      keywords: {
        ...Object.fromEntries(
          DETAIL_FIXED_ROWS.map((row) => [row.key, state.details[row.key]])
        ),
        ...Object.fromEntries(CUSTOM_KEYS.map((ck) => [ck, state.details[ck]])),
      },
      custom_labels: { ...state.customLabels },
    },
  };
}

export async function fetchConditionTemplatesFromApi(): Promise<{
  ok: boolean;
  data?: ConditionTemplateApiResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/condition-templates`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as ConditionTemplateApiResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function saveConditionTemplatesToApi(
  state: ConditionTemplateState
): Promise<{ ok: boolean; message?: string }> {
  const url = `${getApiBaseUrl()}/api/condition-templates`;
  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stateToApiPayload(state)),
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    return { ok: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export async function resetConditionTemplatesOnApi(): Promise<{
  ok: boolean;
  data?: ConditionTemplateApiResponse;
  message?: string;
}> {
  const url = `${getApiBaseUrl()}/api/condition-templates/reset-conditions`;
  try {
    const res = await fetch(url, { method: "POST" });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, message: `HTTP ${res.status}: ${text.slice(0, 120)}` };
    }
    const data = (await res.json()) as ConditionTemplateApiResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}

export type ApiHealthInfo = {
  ok: boolean;
  message: string;
  dbPath?: string;
  dbExists?: boolean;
};

export async function fetchApiHealthDetail(): Promise<ApiHealthInfo> {
  const url = `${getApiBaseUrl()}/health`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, message: `HTTP ${res.status}` };
    }
    const data = await res.json();
    const db = data.db as { hirio_db_path?: string; exists?: boolean } | undefined;
    return {
      ok: true,
      message: "接続OK",
      dbPath: db?.hirio_db_path,
      dbExists: db?.exists,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}
