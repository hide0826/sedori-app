"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import { DATABASE_MENU } from "@/components/menus/menuDummyData";
import {
  fetchProductsFromApi,
  fetchRouteVisitsFromApi,
  fetchStoresFromApi,
  formatYen,
  type DbDataSource,
  type ProductRow,
  type RouteVisitRow,
  type StoreRow,
} from "@/lib/database-api";

const DB_SUB_TABS = [
  { id: "products", label: "商品DB" },
  { id: "stores", label: "店舗マスタ" },
  { id: "visits", label: "ルート訪問DB" },
] as const;

type SubTabId = (typeof DB_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<DbDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

function dummyStores(): StoreRow[] {
  const tab = DATABASE_MENU.tabs.find((t) => t.id === "stores");
  if (!tab) return [];
  return tab.rows.map((row, index) => ({
    id: index + 1,
    store_code: String(row.code ?? ""),
    store_name: String(row.name ?? ""),
    route_code: "",
    affiliated_route_name: String(row.area ?? ""),
    address: "",
    phone: "",
    display_order: null,
    template_include: true,
  }));
}

function dummyProducts(): ProductRow[] {
  const tab = DATABASE_MENU.tabs.find((t) => t.id === "products");
  if (!tab) return [];
  return tab.rows.map((row) => ({
    sku: String(row.sku ?? ""),
    jan: "",
    asin: "",
    product_name: String(row.name ?? ""),
    purchase_date: null,
    purchase_price: Number(row.price ?? 0),
    quantity: 1,
    store_code: "",
    store_name: "",
    listed_date: null,
  }));
}

/**
 * データベース管理（商品DB / 店舗マスタ / ルート訪問DB）。
 * 商品・店舗・ルート訪問は API（hirio.db）優先。
 */
export function DatabaseWorkspace() {
  const [active, setActive] = useState<SubTabId>("stores");
  const [source, setSource] = useState<DbDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [storeTotal, setStoreTotal] = useState(0);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [visits, setVisits] = useState<RouteVisitRow[]>([]);
  const [visitTotal, setVisitTotal] = useState(0);
  const [storeQuery, setStoreQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const loadAll = useCallback(async (q?: string) => {
    setLoading(true);
    setMessage(null);
    const [storesRes, productsRes, visitsRes] = await Promise.all([
      fetchStoresFromApi(q),
      fetchProductsFromApi(),
      fetchRouteVisitsFromApi(),
    ]);

    const errors: string[] = [];

    if (storesRes.ok && storesRes.data) {
      setStores(storesRes.data.stores);
      setStoreTotal(storesRes.data.total);
      setSource("server_db");
      setDbPath(storesRes.data.db_path ?? null);
    } else {
      setStores(dummyStores());
      setStoreTotal(dummyStores().length);
      setSource("dummy");
      setDbPath(null);
      errors.push(storesRes.message ?? "店舗マスタ API に接続できませんでした");
    }

    if (productsRes.ok && productsRes.data) {
      setProducts(productsRes.data.products);
      setProductTotal(productsRes.data.total);
      if (storesRes.ok) {
        setSource("server_db");
        setDbPath(productsRes.data.db_path ?? storesRes.data?.db_path ?? null);
      }
    } else {
      setProducts(dummyProducts());
      setProductTotal(dummyProducts().length);
      errors.push(productsRes.message ?? "商品DB API に接続できませんでした");
    }

    if (visitsRes.ok && visitsRes.data) {
      setVisits(visitsRes.data.visits);
      setVisitTotal(visitsRes.data.total);
      if (storesRes.ok || productsRes.ok) {
        setSource("server_db");
        setDbPath((prev) => prev ?? visitsRes.data?.db_path ?? null);
      }
    } else {
      setVisits([]);
      setVisitTotal(0);
      errors.push(visitsRes.message ?? "ルート訪問DB API に接続できませんでした");
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
        title="データベース管理"
        description="デスクトップの商品DB・店舗マスタ・ルート訪問DBをブラウザで閲覧します（読み取り専用）。"
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
          tabs={DB_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {active === "stores" && (
          <div>
            <div className="mb-4 flex flex-wrap items-end gap-2">
              <label className="text-sm text-[var(--hirio-muted)]">
                検索
                <input
                  className="ml-2 rounded border border-[var(--hirio-line)] bg-white px-2 py-1 text-sm text-[var(--hirio-ink)]"
                  placeholder="店舗名・コード・ルート"
                  value={storeQuery}
                  onChange={(e) => setStoreQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadAll(storeQuery);
                  }}
                />
              </label>
              <button
                type="button"
                className="rounded bg-[var(--hirio-ink)] px-3 py-1 text-sm text-white"
                onClick={() => void loadAll(storeQuery)}
              >
                検索
              </button>
              <button
                type="button"
                className="rounded border border-[var(--hirio-line)] px-3 py-1 text-sm"
                onClick={() => {
                  setStoreQuery("");
                  void loadAll("");
                }}
              >
                クリア
              </button>
            </div>

            {!loading && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">表示件数</div>
                  <div className="mt-1 text-xl font-semibold">{stores.length}</div>
                </div>
                <div className="rounded-lg bg-[var(--hirio-accent-soft)] px-4 py-3 text-center text-[var(--hirio-ok)]">
                  <div className="text-xs opacity-80">マスタ総数</div>
                  <div className="mt-1 text-xl font-semibold">{storeTotal}</div>
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
                      <th className="px-2 py-2 font-medium">コード</th>
                      <th className="px-2 py-2 font-medium">店舗名</th>
                      <th className="px-2 py-2 font-medium">ルート</th>
                      <th className="px-2 py-2 font-medium">エリア／ルート名</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stores.map((row) => (
                      <tr key={row.id ?? row.store_code} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2 font-mono text-xs">{row.store_code || "—"}</td>
                        <td className="px-2 py-2">{row.store_name || "—"}</td>
                        <td className="px-2 py-2">{row.route_code || "—"}</td>
                        <td className="px-2 py-2">{row.affiliated_route_name || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "products" && (
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
                  <div className="text-xs opacity-80">商品総数</div>
                  <div className="mt-1 text-xl font-semibold">{productTotal}</div>
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
                      <th className="px-2 py-2 font-medium">仕入日</th>
                      <th className="px-2 py-2 text-right font-medium">仕入価格</th>
                      <th className="px-2 py-2 font-medium">店舗</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((row) => (
                      <tr key={row.sku} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2 font-mono text-xs">{row.sku}</td>
                        <td className="px-2 py-2">{row.product_name || "—"}</td>
                        <td className="px-2 py-2">{row.purchase_date ?? "—"}</td>
                        <td className="px-2 py-2 text-right">{formatYen(row.purchase_price)}</td>
                        <td className="px-2 py-2">
                          {row.store_name || row.store_code || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {active === "visits" && (
          <div>
            <p className="mb-4 text-sm text-[var(--hirio-muted)]">
              直近 {visits.length} 件を表示します（実訪問のみ・全体 {visitTotal} 件）。
            </p>

            {!loading && (
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg px-4 py-3 text-center">
                  <div className="text-xs text-[var(--hirio-muted)]">表示件数</div>
                  <div className="mt-1 text-xl font-semibold">{visits.length}</div>
                </div>
                <div className="rounded-lg bg-[var(--hirio-accent-soft)] px-4 py-3 text-center text-[var(--hirio-ok)]">
                  <div className="text-xs opacity-80">訪問総数</div>
                  <div className="mt-1 text-xl font-semibold">{visitTotal}</div>
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
                      <th className="px-2 py-2 font-medium">日付</th>
                      <th className="px-2 py-2 font-medium">店舗</th>
                      <th className="px-2 py-2 font-medium">ルート</th>
                      <th className="px-2 py-2 text-right font-medium">滞在(分)</th>
                      <th className="px-2 py-2 text-right font-medium">仕入件数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visits.map((row, i) => (
                      <tr key={`${row.route_date}-${row.store_code}-${i}`} className="border-b border-[var(--hirio-line)]">
                        <td className="px-2 py-2">{row.route_date ?? "—"}</td>
                        <td className="px-2 py-2">{row.store_name || row.store_code || "—"}</td>
                        <td className="px-2 py-2">{row.route_name || row.route_code || "—"}</td>
                        <td className="px-2 py-2 text-right">{row.stay_duration_minutes ?? "—"}</td>
                        <td className="px-2 py-2 text-right">{row.store_item_count ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-[var(--hirio-muted)]">
          読み取り専用です。編集・保存はデスクトップ側が正です。
        </p>
      </div>
    </div>
  );
}
