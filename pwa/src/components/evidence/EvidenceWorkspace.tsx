"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { SubTabs } from "@/components/shell/SubTabs";
import {
  createCreditAccountOnApi,
  createDebitTitleOnApi,
  createExpenseOnApi,
  createJournalEntryOnApi,
  DEFAULT_EXPENSE_CATEGORIES,
  DEFAULT_PAYMENT_METHODS,
  deleteCreditAccountOnApi,
  deleteDebitTitleOnApi,
  deleteExpenseOnApi,
  deleteJournalEntryOnApi,
  fetchCreditAccountsFromApi,
  fetchDebitTitlesFromApi,
  fetchExpensesFromApi,
  fetchJournalEntriesFromApi,
  fetchReceiptsFromApi,
  formatYen,
  updateCreditAccountOnApi,
  updateExpenseOnApi,
  updateJournalEntryOnApi,
  updateReceiptOnApi,
  type AccountTitleRow,
  type CreditAccountRow,
  type ExpensePayload,
  type ExpenseRow,
  type JournalEntry,
  type JournalPayload,
  type ReceiptRow,
  type ReceiptUpdatePayload,
} from "@/lib/evidence-api";
import type { DbDataSource } from "@/lib/database-api";

/** デスクトップ EvidenceManagerWidget と同じ4タブ */
const EVIDENCE_SUB_TABS = [
  { id: "receipts", label: "レシート・領収書・保証書" },
  { id: "expense", label: "経費管理" },
  { id: "accounts", label: "勘定科目設定" },
  { id: "journal", label: "仕訳帳" },
] as const;

type SubTabId = (typeof EVIDENCE_SUB_TABS)[number]["id"];

const SOURCE_LABEL: Record<DbDataSource, string> = {
  server_db: "サーバーDB（hirio.db）",
  dummy: "ダミーデータ",
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function oneYearAgoIso() {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

const EMPTY_EXPENSE = (): ExpensePayload => ({
  expense_date: todayIso(),
  expense_category: "その他",
  account_title: "",
  store_name: "",
  amount: 0,
  quantity: 1,
  unit_price: null,
  payment_method: "現金",
  memo: "",
});

const EMPTY_JOURNAL = (): JournalPayload => ({
  transaction_date: todayIso(),
  debit_account: "仕入",
  amount: 0,
  credit_account: "現金",
  description: "",
  invoice_number: "",
  tax_category: "",
});

const inputCls =
  "mt-1 w-full rounded border border-[var(--hirio-line)] bg-white px-2 py-1 text-sm text-[var(--hirio-ink)]";
const btnPrimary =
  "rounded bg-[var(--hirio-ink)] px-3 py-1.5 text-sm text-white disabled:opacity-50";
const btnGhost =
  "rounded border border-[var(--hirio-line)] px-3 py-1.5 text-sm disabled:opacity-50";

/**
 * デスクトップ証憑管理を踏襲した PWA 版。
 * OCR・一括マッチ・GCS・確定はデスクトップ専用。手動編集はサーバーDBへ。
 */
export function EvidenceWorkspace() {
  const [active, setActive] = useState<SubTabId>("receipts");
  const [source, setSource] = useState<DbDataSource>("dummy");
  const [dbPath, setDbPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const [receipts, setReceipts] = useState<ReceiptRow[]>([]);
  const [receiptTotal, setReceiptTotal] = useState(0);
  const [unmatchedCount, setUnmatchedCount] = useState(0);
  const [editingReceipt, setEditingReceipt] = useState<ReceiptRow | null>(null);

  const [expenses, setExpenses] = useState<ExpenseRow[]>([]);
  const [expenseTotal, setExpenseTotal] = useState(0);
  const [categories, setCategories] = useState(DEFAULT_EXPENSE_CATEGORIES);
  const [payments, setPayments] = useState(DEFAULT_PAYMENT_METHODS);
  const [expenseStart, setExpenseStart] = useState(oneYearAgoIso());
  const [expenseEnd, setExpenseEnd] = useState(todayIso());
  const [expenseForm, setExpenseForm] = useState<ExpensePayload>(EMPTY_EXPENSE());
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);

  const [debitTitles, setDebitTitles] = useState<AccountTitleRow[]>([]);
  const [creditAccounts, setCreditAccounts] = useState<CreditAccountRow[]>([]);
  const [debitName, setDebitName] = useState("");
  const [creditForm, setCreditForm] = useState({
    name: "",
    card_name: "",
    last_four_digits: "",
    is_default: false,
    note: "",
  });
  const [editingCreditId, setEditingCreditId] = useState<number | null>(null);

  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [journalTotal, setJournalTotal] = useState(0);
  const [journalForm, setJournalForm] = useState<JournalPayload>(EMPTY_JOURNAL());
  const [editingJournalId, setEditingJournalId] = useState<number | null>(null);

  const canWrite = source === "server_db";

  const receiptRows = useMemo(
    () => receipts.filter((r) => r.doc_type !== "保証書"),
    [receipts]
  );
  const warrantyRows = useMemo(
    () => receipts.filter((r) => r.doc_type === "保証書"),
    [receipts]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    const [receiptsRes, expensesRes, debitRes, creditRes, journalRes] =
      await Promise.all([
        fetchReceiptsFromApi(),
        fetchExpensesFromApi({ startDate: expenseStart, endDate: expenseEnd }),
        fetchDebitTitlesFromApi(),
        fetchCreditAccountsFromApi(),
        fetchJournalEntriesFromApi(),
      ]);

    const errors: string[] = [];
    let anyOk = false;
    let path: string | null = null;

    if (receiptsRes.ok && receiptsRes.data) {
      setReceipts(receiptsRes.data.receipts);
      setReceiptTotal(receiptsRes.data.total);
      setUnmatchedCount(receiptsRes.data.unmatched_count);
      path = receiptsRes.data.db_path ?? path;
      anyOk = true;
    } else {
      setReceipts([]);
      setReceiptTotal(0);
      setUnmatchedCount(0);
      errors.push(receiptsRes.message ?? "レシート API 失敗");
    }

    if (expensesRes.ok && expensesRes.data) {
      setExpenses(expensesRes.data.expenses);
      setExpenseTotal(expensesRes.data.total);
      if (expensesRes.data.categories?.length) setCategories(expensesRes.data.categories);
      if (expensesRes.data.payment_methods?.length) {
        setPayments(expensesRes.data.payment_methods);
      }
      path = expensesRes.data.db_path ?? path;
      anyOk = true;
    } else {
      setExpenses([]);
      setExpenseTotal(0);
      errors.push(expensesRes.message ?? "経費 API 失敗");
    }

    if (debitRes.ok && debitRes.data) {
      setDebitTitles(debitRes.data.titles);
      path = debitRes.data.db_path ?? path;
      anyOk = true;
    } else {
      setDebitTitles([]);
      errors.push(debitRes.message ?? "借方科目 API 失敗");
    }

    if (creditRes.ok && creditRes.data) {
      setCreditAccounts(creditRes.data.accounts);
      path = creditRes.data.db_path ?? path;
      anyOk = true;
    } else {
      setCreditAccounts([]);
      errors.push(creditRes.message ?? "貸方科目 API 失敗");
    }

    if (journalRes.ok && journalRes.data) {
      setJournalEntries(journalRes.data.entries);
      setJournalTotal(journalRes.data.total);
      path = journalRes.data.db_path ?? path;
      anyOk = true;
    } else {
      setJournalEntries([]);
      setJournalTotal(0);
      errors.push(journalRes.message ?? "仕訳帳 API 失敗");
    }

    setSource(anyOk ? "server_db" : "dummy");
    setDbPath(anyOk ? path : null);
    if (errors.length) setMessage(errors.join(" / "));
    setLoading(false);
  }, [expenseStart, expenseEnd]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const runSave = async (fn: () => Promise<{ ok: boolean; message?: string }>, okMsg: string) => {
    if (!canWrite) {
      setActionMessage("サーバーDB接続中のみ保存できます");
      return;
    }
    setSaving(true);
    setActionMessage(null);
    const res = await fn();
    setActionMessage(res.ok ? okMsg : res.message ?? "失敗しました");
    setSaving(false);
    if (res.ok) await loadAll();
  };

  // ---- Receipt ----
  const saveReceipt = async () => {
    if (!editingReceipt?.id) return;
    const payload: ReceiptUpdatePayload = {
      account_title: editingReceipt.account_title,
      purchase_date: editingReceipt.purchase_date || undefined,
      purchase_time: editingReceipt.purchase_time,
      store_code: editingReceipt.store_code,
      store_name: editingReceipt.store_name,
      phone_number: editingReceipt.phone_number,
      registration_number: editingReceipt.registration_number,
      total_amount: editingReceipt.total_amount,
      discount_amount: editingReceipt.discount_amount,
      linked_skus:
        editingReceipt.account_title.trim() === "仕入"
          ? editingReceipt.linked_skus
          : "",
      price_difference:
        editingReceipt.account_title.trim() === "仕入"
          ? editingReceipt.price_difference
          : 0,
    };
    await runSave(
      () => updateReceiptOnApi(editingReceipt.id!, payload),
      "レシートを更新しました"
    );
    setEditingReceipt(null);
  };

  // ---- Expense ----
  const resetExpenseForm = () => {
    setEditingExpenseId(null);
    setExpenseForm(EMPTY_EXPENSE());
  };

  const startEditExpense = (row: ExpenseRow) => {
    if (row.id == null) return;
    setEditingExpenseId(row.id);
    setExpenseForm({
      expense_date: row.expense_date || todayIso(),
      expense_category: row.expense_category || "その他",
      account_title: row.account_title || "",
      store_name: row.store_name || "",
      amount: row.amount ?? 0,
      quantity: row.quantity || 1,
      unit_price: row.unit_price,
      payment_method: row.payment_method || "現金",
      memo: row.memo || "",
    });
  };

  const saveExpense = async () => {
    const payload: ExpensePayload = {
      ...expenseForm,
      amount: Number(expenseForm.amount) || 0,
      quantity: Number(expenseForm.quantity) || 1,
      unit_price:
        expenseForm.unit_price && expenseForm.unit_price > 0
          ? Number(expenseForm.unit_price)
          : null,
    };
    await runSave(
      () =>
        editingExpenseId != null
          ? updateExpenseOnApi(editingExpenseId, payload)
          : createExpenseOnApi(payload),
      editingExpenseId != null ? "経費を更新しました" : "経費を追加しました"
    );
    resetExpenseForm();
  };

  // ---- Accounts ----
  const addDebit = async () => {
    if (!debitName.trim()) return;
    await runSave(
      () => createDebitTitleOnApi(debitName.trim()),
      "借方科目を追加しました"
    );
    setDebitName("");
  };

  const saveCredit = async () => {
    if (!creditForm.name.trim()) return;
    await runSave(
      () =>
        editingCreditId != null
          ? updateCreditAccountOnApi(editingCreditId, creditForm)
          : createCreditAccountOnApi(creditForm),
      editingCreditId != null ? "貸方科目を更新しました" : "貸方科目を追加しました"
    );
    setEditingCreditId(null);
    setCreditForm({
      name: "",
      card_name: "",
      last_four_digits: "",
      is_default: false,
      note: "",
    });
  };

  const startEditCredit = (row: CreditAccountRow) => {
    if (row.id == null) return;
    setEditingCreditId(row.id);
    setCreditForm({
      name: row.raw_name || row.name,
      card_name: row.card_name || "",
      last_four_digits: row.last_four_digits || "",
      is_default: row.is_default,
      note: row.note || "",
    });
  };

  // ---- Journal ----
  const resetJournalForm = () => {
    setEditingJournalId(null);
    const defaultDebit =
      debitTitles.find((t) => t.name === "仕入")?.name ||
      debitTitles[0]?.name ||
      "仕入";
    const defaultCredit =
      creditAccounts.find((c) => c.is_default)?.raw_name ||
      creditAccounts[0]?.raw_name ||
      "現金";
    setJournalForm({
      ...EMPTY_JOURNAL(),
      debit_account: defaultDebit,
      credit_account: defaultCredit,
    });
  };

  const startEditJournal = (row: JournalEntry) => {
    if (row.id == null) return;
    setEditingJournalId(row.id);
    setJournalForm({
      transaction_date: row.transaction_date || todayIso(),
      debit_account: row.debit_account,
      amount: row.amount ?? 0,
      credit_account: row.credit_account,
      description: row.description,
      invoice_number: row.invoice_number,
      tax_category: row.tax_category,
    });
  };

  const saveJournal = async () => {
    const payload: JournalPayload = {
      ...journalForm,
      amount: Number(journalForm.amount) || 0,
    };
    await runSave(
      () =>
        editingJournalId != null
          ? updateJournalEntryOnApi(editingJournalId, payload)
          : createJournalEntryOnApi(payload),
      editingJournalId != null ? "仕訳を更新しました" : "仕訳を追加しました"
    );
    resetJournalForm();
  };

  return (
    <div>
      <PageHeader
        title="証憑管理"
        description="デスクトップと同じ4タブ（レシート / 経費 / 勘定科目 / 仕訳帳）。OCR・GCS・確定はデスクトップ専用。手動編集はサーバーDBへ保存します。"
      />

      <section className="mb-5 rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-accent-soft)] px-4 py-4 text-sm">
        <p className="font-medium">読み込み元: {SOURCE_LABEL[source]}</p>
        {dbPath && (
          <p className="mt-1 break-all text-xs text-[var(--hirio-muted)]">{dbPath}</p>
        )}
        <p className="mt-2 text-xs text-[var(--hirio-muted)]">
          書き込み: {canWrite ? "有効（サーバー hirio.db）" : "無効"} /
          運用PC本番DBとは別（同期は手動）
        </p>
        {message && <p className="mt-2 text-xs text-amber-700">{message}</p>}
        {actionMessage && (
          <p className="mt-2 text-xs text-[var(--hirio-ok)]">{actionMessage}</p>
        )}
      </section>

      <div className="rounded-lg border border-[var(--hirio-line)] bg-[var(--hirio-surface)] p-4 md:p-6">
        <SubTabs
          tabs={EVIDENCE_SUB_TABS}
          activeId={active}
          onChange={(id) => setActive(id as SubTabId)}
        />

        {loading ? (
          <p className="text-sm text-[var(--hirio-muted)]">読み込み中…</p>
        ) : (
          <>
            {active === "receipts" && (
              <div className="space-y-6">
                <p className="text-sm text-[var(--hirio-muted)]">
                  全体 {receiptTotal} 件（未突合 {unmatchedCount}）。OCRパイプラインはデスクトップ。
                </p>

                {editingReceipt && (
                  <div className="space-y-3 border-b border-[var(--hirio-line)] pb-6">
                    <p className="text-sm font-medium">
                      レシート編集（id={editingReceipt.id}）— デスクトップ詳細ダイアログ相当
                    </p>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="text-sm text-[var(--hirio-muted)]">
                        科目
                        <input
                          className={inputCls}
                          list="debit-title-options"
                          value={editingReceipt.account_title}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              account_title: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        日付
                        <input
                          className={inputCls}
                          value={editingReceipt.purchase_date || ""}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              purchase_date: e.target.value,
                            })
                          }
                          placeholder="yyyy-MM-dd または yyyy/MM/dd"
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        時刻
                        <input
                          className={inputCls}
                          value={editingReceipt.purchase_time}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              purchase_time: e.target.value,
                            })
                          }
                          placeholder="HH:MM"
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        店舗名
                        <input
                          className={inputCls}
                          value={editingReceipt.store_name}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              store_name: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        店舗コード
                        <input
                          className={inputCls}
                          value={editingReceipt.store_code}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              store_code: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        電話番号
                        <input
                          className={inputCls}
                          value={editingReceipt.phone_number}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              phone_number: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        登録番号
                        <input
                          className={inputCls}
                          value={editingReceipt.registration_number}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              registration_number: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        合計
                        <input
                          type="number"
                          className={inputCls}
                          value={editingReceipt.total_amount ?? 0}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              total_amount: Number(e.target.value) || 0,
                            })
                          }
                        />
                      </label>
                      <label className="text-sm text-[var(--hirio-muted)]">
                        値引
                        <input
                          type="number"
                          className={inputCls}
                          value={editingReceipt.discount_amount ?? 0}
                          onChange={(e) =>
                            setEditingReceipt({
                              ...editingReceipt,
                              discount_amount: Number(e.target.value) || 0,
                            })
                          }
                        />
                      </label>
                      {editingReceipt.account_title.trim() === "仕入" && (
                        <label className="text-sm text-[var(--hirio-muted)] md:col-span-2">
                          紐付けSKU（カンマ区切り）
                          <input
                            className={inputCls}
                            value={editingReceipt.linked_skus}
                            onChange={(e) =>
                              setEditingReceipt({
                                ...editingReceipt,
                                linked_skus: e.target.value,
                              })
                            }
                          />
                        </label>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <button type="button" className={btnPrimary} disabled={saving} onClick={() => void saveReceipt()}>
                        保存
                      </button>
                      <button type="button" className={btnGhost} onClick={() => setEditingReceipt(null)}>
                        キャンセル
                      </button>
                    </div>
                  </div>
                )}

                <div>
                  <p className="mb-2 text-xs font-medium text-[var(--hirio-muted)]">
                    レシート一覧（{receiptRows.length}）
                  </p>
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse text-left text-sm">
                      <thead>
                        <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                          <th className="px-2 py-2">科目</th>
                          <th className="px-2 py-2">日付</th>
                          <th className="px-2 py-2">店舗名</th>
                          <th className="px-2 py-2 text-right">合計</th>
                          <th className="px-2 py-2">突合</th>
                          <th className="px-2 py-2">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {receiptRows.map((row) => (
                          <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                            <td className="px-2 py-2">{row.account_title || "—"}</td>
                            <td className="px-2 py-2">{row.purchase_date ?? "—"}</td>
                            <td className="px-2 py-2">{row.store_name || "—"}</td>
                            <td className="px-2 py-2 text-right">{formatYen(row.total_amount)}</td>
                            <td className="px-2 py-2">{row.match_status}</td>
                            <td className="px-2 py-2">
                              <button
                                type="button"
                                className="text-xs text-[var(--hirio-accent)] disabled:opacity-40"
                                disabled={!canWrite || row.id == null}
                                onClick={() => setEditingReceipt({ ...row })}
                              >
                                編集
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-xs font-medium text-[var(--hirio-muted)]">
                    保証書一覧（{warrantyRows.length}）
                  </p>
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse text-left text-sm">
                      <thead>
                        <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                          <th className="px-2 py-2">日付</th>
                          <th className="px-2 py-2">店舗</th>
                          <th className="px-2 py-2">SKU</th>
                          <th className="px-2 py-2">商品名</th>
                          <th className="px-2 py-2">保証最終日</th>
                          <th className="px-2 py-2">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {warrantyRows.map((row) => (
                          <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                            <td className="px-2 py-2">{row.purchase_date ?? "—"}</td>
                            <td className="px-2 py-2">{row.store_name || "—"}</td>
                            <td className="px-2 py-2 font-mono text-xs">{row.sku || "—"}</td>
                            <td className="px-2 py-2">{row.product_name || "—"}</td>
                            <td className="px-2 py-2">{row.warranty_until || "—"}</td>
                            <td className="px-2 py-2">
                              <button
                                type="button"
                                className="text-xs text-[var(--hirio-accent)] disabled:opacity-40"
                                disabled={!canWrite || row.id == null}
                                onClick={() => setEditingReceipt({ ...row })}
                              >
                                編集
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {active === "expense" && (
              <div>
                <div className="mb-4 flex flex-wrap items-end gap-2">
                  <label className="text-sm text-[var(--hirio-muted)]">
                    期間
                    <input
                      type="date"
                      className={`${inputCls} ml-2 w-auto`}
                      value={expenseStart}
                      onChange={(e) => setExpenseStart(e.target.value)}
                    />
                  </label>
                  <span className="text-sm text-[var(--hirio-muted)]">〜</span>
                  <input
                    type="date"
                    className={`${inputCls} mt-0 w-auto`}
                    value={expenseEnd}
                    onChange={(e) => setExpenseEnd(e.target.value)}
                  />
                  <button type="button" className={btnGhost} onClick={() => void loadAll()}>
                    フィルタ
                  </button>
                </div>

                <div className="mb-6 space-y-3 border-b border-[var(--hirio-line)] pb-6">
                  <p className="text-sm font-medium">
                    {editingExpenseId != null
                      ? `経費を編集（id=${editingExpenseId}）`
                      : "経費を追加"}
                  </p>
                  <div className="grid gap-3 md:grid-cols-3">
                    <label className="text-sm text-[var(--hirio-muted)]">
                      日付
                      <input
                        type="date"
                        className={inputCls}
                        value={expenseForm.expense_date}
                        onChange={(e) =>
                          setExpenseForm({ ...expenseForm, expense_date: e.target.value })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      カテゴリ
                      <select
                        className={inputCls}
                        value={expenseForm.expense_category}
                        onChange={(e) =>
                          setExpenseForm({
                            ...expenseForm,
                            expense_category: e.target.value,
                          })
                        }
                      >
                        {categories.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      勘定科目
                      <input
                        className={inputCls}
                        list="debit-title-options"
                        value={expenseForm.account_title}
                        onChange={(e) =>
                          setExpenseForm({ ...expenseForm, account_title: e.target.value })
                        }
                        placeholder="空ならカテゴリをコピー"
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      支払先名
                      <input
                        className={inputCls}
                        value={expenseForm.store_name}
                        onChange={(e) =>
                          setExpenseForm({ ...expenseForm, store_name: e.target.value })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      金額
                      <input
                        type="number"
                        min={0}
                        className={inputCls}
                        value={expenseForm.amount}
                        onChange={(e) =>
                          setExpenseForm({
                            ...expenseForm,
                            amount: Number(e.target.value) || 0,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      数量
                      <input
                        type="number"
                        min={1}
                        className={inputCls}
                        value={expenseForm.quantity ?? 1}
                        onChange={(e) =>
                          setExpenseForm({
                            ...expenseForm,
                            quantity: Number(e.target.value) || 1,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      単価
                      <input
                        type="number"
                        min={0}
                        className={inputCls}
                        value={expenseForm.unit_price ?? 0}
                        onChange={(e) =>
                          setExpenseForm({
                            ...expenseForm,
                            unit_price: Number(e.target.value) || 0,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      支払方法
                      <select
                        className={inputCls}
                        value={expenseForm.payment_method}
                        onChange={(e) =>
                          setExpenseForm({
                            ...expenseForm,
                            payment_method: e.target.value,
                          })
                        }
                      >
                        {payments.map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)] md:col-span-3">
                      メモ
                      <input
                        className={inputCls}
                        value={expenseForm.memo}
                        onChange={(e) =>
                          setExpenseForm({ ...expenseForm, memo: e.target.value })
                        }
                      />
                    </label>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" className={btnPrimary} disabled={!canWrite || saving} onClick={() => void saveExpense()}>
                      {editingExpenseId != null ? "更新" : "追加"}
                    </button>
                    {editingExpenseId != null && (
                      <button type="button" className={btnGhost} onClick={resetExpenseForm}>
                        キャンセル
                      </button>
                    )}
                  </div>
                </div>

                <p className="mb-2 text-sm text-[var(--hirio-muted)]">
                  {expenses.length} 件表示（期間内 {expenseTotal} 件）
                </p>
                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                        <th className="px-2 py-2">日付</th>
                        <th className="px-2 py-2">カテゴリ</th>
                        <th className="px-2 py-2">勘定科目</th>
                        <th className="px-2 py-2">支払先</th>
                        <th className="px-2 py-2 text-right">金額</th>
                        <th className="px-2 py-2 text-right">数量</th>
                        <th className="px-2 py-2">支払方法</th>
                        <th className="px-2 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {expenses.map((row) => (
                        <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                          <td className="px-2 py-2">{row.expense_date ?? "—"}</td>
                          <td className="px-2 py-2">{row.expense_category}</td>
                          <td className="px-2 py-2">{row.account_title || "—"}</td>
                          <td className="px-2 py-2">{row.store_name || "—"}</td>
                          <td className="px-2 py-2 text-right">{formatYen(row.amount)}</td>
                          <td className="px-2 py-2 text-right">{row.quantity}</td>
                          <td className="px-2 py-2">{row.payment_method || "—"}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="text-xs text-[var(--hirio-accent)] disabled:opacity-40"
                                disabled={!canWrite || row.id == null || saving}
                                onClick={() => startEditExpense(row)}
                              >
                                編集
                              </button>
                              <button
                                type="button"
                                className="text-xs text-amber-700 disabled:opacity-40"
                                disabled={!canWrite || row.id == null || saving}
                                onClick={() => {
                                  if (row.id == null) return;
                                  if (!window.confirm("削除しますか？")) return;
                                  void runSave(
                                    () => deleteExpenseOnApi(row.id!),
                                    "経費を削除しました"
                                  );
                                }}
                              >
                                削除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {active === "accounts" && (
              <div className="space-y-8">
                <div>
                  <p className="mb-2 text-xs font-medium text-[var(--hirio-muted)]">
                    借方勘定科目（追加・削除のみ / デスクトップ同様）
                  </p>
                  <div className="mb-3 flex flex-wrap items-end gap-2">
                    <label className="text-sm text-[var(--hirio-muted)]">
                      科目名
                      <input
                        className={`${inputCls} ml-2 w-48`}
                        value={debitName}
                        onChange={(e) => setDebitName(e.target.value)}
                        placeholder="例: 仕入"
                      />
                    </label>
                    <button
                      type="button"
                      className={btnPrimary}
                      disabled={!canWrite || saving || !debitName.trim()}
                      onClick={() => void addDebit()}
                    >
                      追加
                    </button>
                  </div>
                  <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                        <th className="px-2 py-2">科目名</th>
                        <th className="px-2 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {debitTitles.map((row) => (
                        <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                          <td className="px-2 py-2">{row.name}</td>
                          <td className="px-2 py-2">
                            <button
                              type="button"
                              className="text-xs text-amber-700 disabled:opacity-40"
                              disabled={!canWrite || row.id == null || saving}
                              onClick={() => {
                                if (row.id == null) return;
                                if (!window.confirm("削除しますか？")) return;
                                void runSave(
                                  () => deleteDebitTitleOnApi(row.id!),
                                  "借方科目を削除しました"
                                );
                              }}
                            >
                              削除
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <p className="mb-2 text-xs font-medium text-[var(--hirio-muted)]">
                    貸方勘定科目（追加・編集・削除）
                  </p>
                  <div className="mb-3 grid gap-2 md:grid-cols-4">
                    <label className="text-sm text-[var(--hirio-muted)]">
                      科目名
                      <input
                        className={inputCls}
                        list="debit-title-options"
                        value={creditForm.name}
                        onChange={(e) =>
                          setCreditForm({ ...creditForm, name: e.target.value })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      カード名
                      <input
                        className={inputCls}
                        value={creditForm.card_name}
                        onChange={(e) =>
                          setCreditForm({ ...creditForm, card_name: e.target.value })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      下4桁
                      <input
                        className={inputCls}
                        maxLength={4}
                        value={creditForm.last_four_digits}
                        onChange={(e) =>
                          setCreditForm({
                            ...creditForm,
                            last_four_digits: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label className="flex items-end gap-2 pb-1 text-sm text-[var(--hirio-muted)]">
                      <input
                        type="checkbox"
                        checked={creditForm.is_default}
                        onChange={(e) =>
                          setCreditForm({
                            ...creditForm,
                            is_default: e.target.checked,
                          })
                        }
                      />
                      デフォルト
                    </label>
                  </div>
                  <div className="mb-3 flex gap-2">
                    <button
                      type="button"
                      className={btnPrimary}
                      disabled={!canWrite || saving || !creditForm.name.trim()}
                      onClick={() => void saveCredit()}
                    >
                      {editingCreditId != null ? "更新" : "追加"}
                    </button>
                    {editingCreditId != null && (
                      <button
                        type="button"
                        className={btnGhost}
                        onClick={() => {
                          setEditingCreditId(null);
                          setCreditForm({
                            name: "",
                            card_name: "",
                            last_four_digits: "",
                            is_default: false,
                            note: "",
                          });
                        }}
                      >
                        キャンセル
                      </button>
                    )}
                  </div>
                  <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                        <th className="px-2 py-2">科目名</th>
                        <th className="px-2 py-2">カード</th>
                        <th className="px-2 py-2">デフォルト</th>
                        <th className="px-2 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {creditAccounts.map((row) => (
                        <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                          <td className="px-2 py-2">{row.name}</td>
                          <td className="px-2 py-2">{row.card_name || "—"}</td>
                          <td className="px-2 py-2">{row.is_default ? "✓" : "—"}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="text-xs text-[var(--hirio-accent)] disabled:opacity-40"
                                disabled={!canWrite || row.id == null}
                                onClick={() => startEditCredit(row)}
                              >
                                編集
                              </button>
                              <button
                                type="button"
                                className="text-xs text-amber-700 disabled:opacity-40"
                                disabled={!canWrite || row.id == null || saving}
                                onClick={() => {
                                  if (row.id == null) return;
                                  if (!window.confirm("削除しますか？")) return;
                                  void runSave(
                                    () => deleteCreditAccountOnApi(row.id!),
                                    "貸方科目を削除しました"
                                  );
                                }}
                              >
                                削除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {active === "journal" && (
              <div>
                <div className="mb-6 space-y-3 border-b border-[var(--hirio-line)] pb-6">
                  <p className="text-sm font-medium">
                    {editingJournalId != null
                      ? `仕訳を編集（id=${editingJournalId}）`
                      : "仕訳を追加"}
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="text-sm text-[var(--hirio-muted)]">
                      取引日付
                      <input
                        type="date"
                        className={inputCls}
                        value={journalForm.transaction_date}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            transaction_date: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      金額
                      <input
                        type="number"
                        min={0}
                        className={inputCls}
                        value={journalForm.amount}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            amount: Number(e.target.value) || 0,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      借方勘定科目
                      <select
                        className={inputCls}
                        value={journalForm.debit_account}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            debit_account: e.target.value,
                          })
                        }
                      >
                        {debitTitles.map((t) => (
                          <option key={t.id ?? t.name} value={t.name}>
                            {t.name}
                          </option>
                        ))}
                        {!debitTitles.some((t) => t.name === journalForm.debit_account) &&
                          journalForm.debit_account && (
                            <option value={journalForm.debit_account}>
                              {journalForm.debit_account}
                            </option>
                          )}
                      </select>
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      貸方勘定科目
                      <select
                        className={inputCls}
                        value={journalForm.credit_account}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            credit_account: e.target.value,
                          })
                        }
                      >
                        {creditAccounts.map((c) => (
                          <option key={c.id ?? c.raw_name} value={c.raw_name}>
                            {c.name}
                          </option>
                        ))}
                        {!creditAccounts.some(
                          (c) => c.raw_name === journalForm.credit_account
                        ) &&
                          journalForm.credit_account && (
                            <option value={journalForm.credit_account}>
                              {journalForm.credit_account}
                            </option>
                          )}
                      </select>
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)] md:col-span-2">
                      摘要
                      <input
                        className={inputCls}
                        value={journalForm.description}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            description: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      インボイス番号
                      <input
                        className={inputCls}
                        value={journalForm.invoice_number}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            invoice_number: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label className="text-sm text-[var(--hirio-muted)]">
                      税区分
                      <input
                        className={inputCls}
                        value={journalForm.tax_category}
                        onChange={(e) =>
                          setJournalForm({
                            ...journalForm,
                            tax_category: e.target.value,
                          })
                        }
                      />
                    </label>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className={btnPrimary}
                      disabled={!canWrite || saving}
                      onClick={() => void saveJournal()}
                    >
                      {editingJournalId != null ? "更新" : "追加"}
                    </button>
                    {editingJournalId != null && (
                      <button type="button" className={btnGhost} onClick={resetJournalForm}>
                        キャンセル
                      </button>
                    )}
                  </div>
                </div>

                <p className="mb-2 text-sm text-[var(--hirio-muted)]">
                  {journalEntries.length} 件表示（全体 {journalTotal} 件）
                </p>
                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[var(--hirio-line)] text-[var(--hirio-muted)]">
                        <th className="px-2 py-2">日付</th>
                        <th className="px-2 py-2">借方</th>
                        <th className="px-2 py-2 text-right">金額</th>
                        <th className="px-2 py-2">貸方</th>
                        <th className="px-2 py-2">摘要</th>
                        <th className="px-2 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {journalEntries.map((row) => (
                        <tr key={row.id} className="border-b border-[var(--hirio-line)]">
                          <td className="px-2 py-2">{row.transaction_date ?? "—"}</td>
                          <td className="px-2 py-2">{row.debit_account}</td>
                          <td className="px-2 py-2 text-right">{formatYen(row.amount)}</td>
                          <td className="px-2 py-2">{row.credit_account}</td>
                          <td className="px-2 py-2">{row.description || "—"}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="text-xs text-[var(--hirio-accent)] disabled:opacity-40"
                                disabled={!canWrite || row.id == null}
                                onClick={() => startEditJournal(row)}
                              >
                                編集
                              </button>
                              <button
                                type="button"
                                className="text-xs text-amber-700 disabled:opacity-40"
                                disabled={!canWrite || row.id == null || saving}
                                onClick={() => {
                                  if (row.id == null) return;
                                  if (!window.confirm("削除しますか？")) return;
                                  void runSave(
                                    () => deleteJournalEntryOnApi(row.id!),
                                    "仕訳を削除しました"
                                  );
                                }}
                              >
                                削除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <datalist id="debit-title-options">
        {debitTitles.map((t) => (
          <option key={t.id ?? t.name} value={t.name} />
        ))}
      </datalist>
    </div>
  );
}
