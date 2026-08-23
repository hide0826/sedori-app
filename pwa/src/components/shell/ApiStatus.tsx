"use client";

import { useEffect, useState } from "react";
import { checkApiHealth, getApiBaseUrl } from "@/lib/api-config";

type Status = "checking" | "ok" | "error";

export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");
  const [detail, setDetail] = useState("確認中…");
  const [baseUrl, setBaseUrl] = useState("");

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      const url = getApiBaseUrl();
      if (!cancelled) {
        setBaseUrl(url);
        setStatus("checking");
        setDetail("確認中…");
      }

      const result = await checkApiHealth(url);
      if (cancelled) return;

      setStatus(result.ok ? "ok" : "error");
      setDetail(result.message);
    };

    run();
    const timer = window.setInterval(run, 30000);

    const onStorage = (event: StorageEvent) => {
      if (event.key === "hirio.apiBaseUrl") {
        run();
      }
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener("hirio-api-config-changed", run);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("hirio-api-config-changed", run);
    };
  }, []);

  const dotClass =
    status === "ok"
      ? "bg-[var(--hirio-ok)]"
      : status === "error"
        ? "bg-[var(--hirio-danger)]"
        : "bg-amber-400";

  return (
    <div className="space-y-1 text-xs">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotClass}`} />
        <span className="font-medium text-white/90">
          {status === "ok" ? "API 接続OK" : status === "error" ? "API 未接続" : "API 確認中"}
        </span>
      </div>
      <p className="truncate text-white/45" title={baseUrl}>
        {baseUrl || "…"}
      </p>
      {status === "error" && (
        <p className="text-white/45">{detail}</p>
      )}
    </div>
  );
}
