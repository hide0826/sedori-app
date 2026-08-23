const STORAGE_KEY = "hirio.apiBaseUrl";
const DEFAULT_API_BASE_URL = "http://localhost:8000";

function isLoopbackUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "::1";
  } catch {
    return /localhost|127\.0\.0\.1/.test(url);
  }
}

function inferApiBaseUrlFromBrowser(): string | null {
  if (typeof window === "undefined") return null;
  const host = window.location.hostname;
  if (!host || host === "localhost" || host === "127.0.0.1" || host === "::1") {
    return null;
  }
  // メインPCから http://192.168.x.x:3000 で開いたときは、同じホストの :8000 を API にする
  return `http://${host}:8000`;
}

export function getDefaultApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  return inferApiBaseUrlFromBrowser() || DEFAULT_API_BASE_URL;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL;
  }

  const inferred = inferApiBaseUrlFromBrowser();
  const stored = window.localStorage.getItem(STORAGE_KEY)?.trim();

  // リモート（LAN）から開いているのに localhost が保存されている場合は無視する
  if (inferred && stored && isLoopbackUrl(stored)) {
    return inferred;
  }

  if (stored) {
    return stored.replace(/\/$/, "");
  }

  return getDefaultApiBaseUrl();
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
