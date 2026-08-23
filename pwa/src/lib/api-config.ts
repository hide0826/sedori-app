const STORAGE_KEY = "hirio.apiBaseUrl";
const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function getDefaultApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return getDefaultApiBaseUrl();
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return (stored && stored.trim()) || getDefaultApiBaseUrl();
}

export function setApiBaseUrl(url: string): void {
  const trimmed = url.trim().replace(/\/$/, "");
  window.localStorage.setItem(STORAGE_KEY, trimmed);
}

export async function checkApiHealth(
  baseUrl: string = getApiBaseUrl(),
): Promise<{ ok: boolean; message: string }> {
  const url = `${baseUrl.replace(/\/$/, "")}/health`;
  try {
    const response = await fetch(url, { method: "GET", cache: "no-store" });
    if (!response.ok) {
      return { ok: false, message: `HTTP ${response.status}` };
    }
    return { ok: true, message: "接続OK" };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, message };
  }
}
