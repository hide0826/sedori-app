"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import { IMAGES_MENU } from "@/components/menus/menuDummyData";
import {
  fetchProductImagesFromApi,
  fetchScannedImagesFromApi,
  type ProductImageRow,
  type ScannedImageRow,
} from "@/lib/images-api";
import type { DbDataSource } from "@/lib/database-api";

const IMAGE_SUB_TABS = [
  { id: "manage", label: "画像管理" },
  { id: "register", label: "画像登録" },
] as const;

type SubTabId = (typeof IMAGE_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<DbDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

function dummyProducts(): ProductImageRow[] {
  const tab = IMAGES_MENU.tabs.find((t) => t.id === "manage");
  if (!tab) return [];
  return tab.rows.map((row) => ({
    sku: String(row.sku ?? ""),
    product_name: String(row.name ?? ""),
    jan: "",
    image_count: Number(row.images ?? 0),
    has_urls: false,
    status: String(row.status ?? ""),
  }));
}

/**
 * 画像管理（商品別画像枚数 / スキャン済みファイル一覧）。
 * hirio.db 読み取り専用。アップロード・確定処理はデスクトップが正。
 */
export function ImagesWorkspace() {
  const [active, setActive] = useState<SubTabId>("manage");
  const [source, setSource] = useState<DbDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [products, setProducts] = useState<ProductImageRow[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [registeredCount, setRegisteredCount] = useState(0);
  const [unregisteredCount, setUnregisteredCount] = useState(0);
  const [scanned, setScanned] = useState<ScannedImageRow[]>([]);
  const [scannedTotal, setScannedTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const registerTab = IMAGES_MENU.tabs.find((t) => t.id === "register");

  const loadAll = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    const [productsRes, scannedRes] = await Promise.all([
      fetchProductImagesFromApi(),
      fetchScannedImagesFromApi(),
    ]);

    const errors: string[] = [];

    if (productsRes.ok && productsRes.data) {
      setProducts(productsRes.data.items);
      setProductTotal(productsRes.data.total);
      setRegisteredCount(productsRes.data.registered_count);
      setUnregisteredCount(productsRes.data.unregistered_count);
      setSource("server_db");
      setDbPath(productsRes.data.db_path ?? null);
    } else {
      setProducts(dummyProducts());
      setProductTotal(dummyProducts().length);
      setRegisteredCount(dummyProducts().filter((p) => p.status === "登録済").length);
      setUnregisteredCount(dummyProducts().filter((p) => p.status === "未登録").length);
      setSource("dummy");
      setDbPath(null);
      errors.push(productsRes.message ?? "画像管理 API に接続できませんでした");
    }

    if (scannedRes.ok && scannedRes.data) {
      setScanned(scannedRes.data.items);
      setScannedTotal(scannedRes.data.total);
      if (productsRes.ok) {
        setSource("server_db");
        setDbPath((prev) => prev ?? scannedRes.data?.db_path ?? null);
      }
    } else {
      setScanned([]);
      setScannedTotal(0);
      errors.push(scannedRes.message ?? "スキャン画像 API に接続できませんでした");
    }

    if (errors.length > 0) {
      setMessage(errors.join(" / "));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  return (
    <div>
      <PageHeader
        title="画像管理"
        description="商品ごとの画像登録状況とスキャン済みファイルをブラウザで閲覧します（読み取り専用）。アップロード・確定処理はデスクトップが正です。"
      />

      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm text-[var(--hirio-ink)]">
        <p className="font-medium">読み込み元: {SOURCE_LABEL[source]}</p>
        {dbPath && (
          <p className="mt-1 break-all text-xs text-[var(--hirio-muted)]">{dbPath}</p>
        )}
        {message && <p className="mt-2 text-xs text-amber-700">{message}</p>}
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={IMAGE_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {active === "manage" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              直近 {products.length} 件を表示します（全体 {productTotal} 件）。
            </p>

            {!loading && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">表示件数</div>
                  <div className="mt-1 text-xl font-semibold">{products.length}</div>
                </div>
                <div className="rounded-lg bg-[var(--hirio-accent-soft)] px-4 py-3 text-center text-[var(--hirio-ok)]">
                  <div className="text-xs opacity-80">登録済</div>
                  <div className="mt-1 text-xl font-semibold">{registeredCount}</div>
                </div>
                <div className="rounded-lg bg-amber-50 px-4 py-3 text-center text-amber-700">
                  <div className="text-xs opacity-80">未登録</div>
                  <div className="mt-1 text-xl font-semibold">{unregisteredCount}</div>
                </div>
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">スキャン済</div>
                  <div className="mt-1 text-xl font-semibold">{scannedTotal}</div>
                </div>
              </div>
            )}

            {loading ? (
              <p className="text-sm text-[var(--hirio-muted)]">読み込み中…</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">SKU</th>
                      <th className="px-2 py-2 font-medium">商品名</th>
                      <th className="px-2 py-2 font-medium">JAN</th>
                      <th className="px-2 py-2 text-right font-medium">画像枚数</th>
                      <th className="px-2 py-2 font-medium">状態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((row) => (
                      <tr key={row.sku} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2 font-mono text-xs">{row.sku || "—"}</td>
                        <td className="px-2 py-2">{row.product_name || "—"}</td>
                        <td className="px-2 py-2 font-mono text-xs">{row.jan || "—"}</td>
                        <td className="px-2 py-2 text-right">{row.image_count}</td>
                        <td className="px-2 py-2">
                          <span
                            className={
                              row.status === "登録済"
                                ? "text-[var(--hirio-ok)]"
                                : row.status === "未登録"
                                  ? "text-amber-700"
                                  : ""
                            }
                          >
                            {row.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "register" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              ドラッグ登録・GCSアップロード・確定処理はデスクトップ側で行います。
              スキャン済みファイル {scannedTotal} 件（直近 {scanned.length} 件を表示）。
            </p>

            {registerTab?.rows && (
              <div className="mb-4 overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">枠</th>
                      <th className="px-2 py-2 font-medium">説明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {registerTab.rows.map((row) => (
                      <tr key={String(row.slot)} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{row.slot}</td>
                        <td className="px-2 py-2 text-[var(--hirio-muted)]">{row.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {loading ? (
              <p className="text-sm text-[var(--hirio-muted)]">読み込み中…</p>
            ) : scanned.length > 0 ? (
              <div className="overflow-x-auto">
                <p className="mb-2 text-xs font-medium text-[var(--hirio-muted)]">
                  スキャン済みファイル（product_images）
                </p>
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                      <th className="px-2 py-2 font-medium">JAN</th>
                      <th className="px-2 py-2 font-medium">ファイル名</th>
                      <th className="px-2 py-2 font-medium">撮影時刻</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanned.map((row) => (
                      <tr key={row.id ?? row.file_path} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2 font-mono text-xs">{row.jan || "—"}</td>
                        <td className="px-2 py-2 text-xs">{row.file_name || "—"}</td>
                        <td className="px-2 py-2">{row.capture_time ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-[var(--hirio-muted)]">スキャン済みファイルはありません。</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
