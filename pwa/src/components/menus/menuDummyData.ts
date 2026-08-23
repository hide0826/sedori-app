export type MenuColumn = {
  key: string;
  label: string;
  align?: "left" | "right";
};

export type MenuSummaryCard = {
  label: string;
  value: string | number;
  tone?: "default" | "ok" | "warn";
};

export type MenuTabConfig = {
  id: string;
  label: string;
  hint?: string;
  columns: MenuColumn[];
  rows: Record<string, string | number>[];
  summary?: MenuSummaryCard[];
};

export type ThinMenuConfig = {
  title: string;
  description: string;
  note?: string;
  tabs: MenuTabConfig[];
};

export const ROUTE_MENU: ThinMenuConfig = {
  title: "ルート",
  description:
    "デスクトップの「ルート選択」「ルートサマリー」に相当する薄い版です。本番データは未接続です。",
  note: "ダミーの店舗訪問計画とサマリーを表示します。IN/OUT や時刻突合はこれから載せます。",
  tabs: [
    {
      id: "select",
      label: "ルート選択",
      hint: "今日のルート候補（ダミー）",
      columns: [
        { key: "date", label: "日付" },
        { key: "route", label: "ルート名" },
        { key: "stores", label: "店舗数", align: "right" },
        { key: "status", label: "状態" },
      ],
      rows: [
        {
          date: "2026-08-23",
          route: "玉川口ルート（ダミー）",
          stores: 6,
          status: "下書き",
        },
        {
          date: "2026-08-22",
          route: "川崎北部ルート（ダミー）",
          stores: 5,
          status: "完了",
        },
      ],
      summary: [
        { label: "今週のルート", value: 2 },
        { label: "未完了", value: 1, tone: "warn" },
      ],
    },
    {
      id: "summary",
      label: "ルートサマリー",
      hint: "店舗ごとの訪問メモ（ダミー）",
      columns: [
        { key: "store", label: "店舗" },
        { key: "in", label: "IN" },
        { key: "out", label: "OUT" },
        { key: "purchases", label: "仕入件数", align: "right" },
        { key: "memo", label: "メモ" },
      ],
      rows: [
        {
          store: "ブックオフ玉川",
          in: "10:12",
          out: "10:48",
          purchases: 3,
          memo: "フィギュア中心",
        },
        {
          store: "ハードオフ川崎",
          in: "11:05",
          out: "11:40",
          purchases: 1,
          memo: "家電は見送り",
        },
        {
          store: "セカンドストリート",
          in: "12:10",
          out: "12:55",
          purchases: 2,
          memo: "レゴ候補あり",
        },
      ],
    },
  ],
};

export const DATABASE_MENU: ThinMenuConfig = {
  title: "データベース管理",
  description:
    "デスクトップの商品DB・店舗マスタ・ルート訪問DBに相当する薄い版です。読み取り専用のダミー一覧です。",
  tabs: [
    {
      id: "products",
      label: "商品DB",
      hint: "仕入DBの一部イメージ（ダミー）",
      columns: [
        { key: "sku", label: "SKU" },
        { key: "name", label: "商品名" },
        { key: "condition", label: "コンディション" },
        { key: "price", label: "仕入価格", align: "right" },
        { key: "status", label: "状態" },
      ],
      rows: [
        {
          sku: "250820-FIG-001",
          name: "ダミーフィギュアA",
          condition: "中古(良い)",
          price: 800,
          status: "在庫",
        },
        {
          sku: "250821-FIG-002",
          name: "ダミーフィギュアB",
          condition: "中古(非常に良い)",
          price: 1200,
          status: "出品準備",
        },
      ],
      summary: [
        { label: "表示件数", value: 2 },
        { label: "在庫", value: 1, tone: "ok" },
      ],
    },
    {
      id: "stores",
      label: "店舗マスタ",
      columns: [
        { key: "code", label: "コード" },
        { key: "name", label: "店舗名" },
        { key: "area", label: "エリア" },
        { key: "chain", label: "チェーン" },
      ],
      rows: [
        { code: "BO-TG", name: "ブックオフ玉川", area: "東京", chain: "BookOff" },
        { code: "HO-KW", name: "ハードオフ川崎", area: "神奈川", chain: "HardOff" },
        { code: "2nd-ST", name: "セカンドストリート", area: "神奈川", chain: "2ndStreet" },
      ],
    },
    {
      id: "visits",
      label: "ルート訪問DB",
      columns: [
        { key: "date", label: "日付" },
        { key: "store", label: "店舗" },
        { key: "route", label: "ルート" },
        { key: "duration", label: "滞在(分)", align: "right" },
      ],
      rows: [
        {
          date: "2026-08-23",
          store: "ブックオフ玉川",
          route: "玉川口ルート",
          duration: 36,
        },
        {
          date: "2026-08-23",
          store: "ハードオフ川崎",
          route: "玉川口ルート",
          duration: 35,
        },
      ],
    },
  ],
};

export const ANTIQUE_MENU: ThinMenuConfig = {
  title: "古物台帳",
  description:
    "デスクトップの古物台帳（入力・閲覧）に相当する薄い版です。台帳出力はこれから載せます。",
  tabs: [
    {
      id: "ledger",
      label: "閲覧・出力",
      hint: "登録済み古物の一覧イメージ（ダミー）",
      columns: [
        { key: "date", label: "受入日" },
        { key: "name", label: "品名" },
        { key: "feature", label: "特徴" },
        { key: "seller", label: "売主" },
        { key: "price", label: "代価", align: "right" },
      ],
      rows: [
        {
          date: "2026-08-20",
          name: "フィギュア（ダミー）",
          feature: "箱あり・付属品完備",
          seller: "ブックオフ玉川",
          price: 800,
        },
        {
          date: "2026-08-21",
          name: "ゲームソフト（ダミー）",
          feature: "ディスクのみ",
          seller: "ハードオフ川崎",
          price: 500,
        },
      ],
      summary: [{ label: "今月の登録", value: 2 }],
    },
    {
      id: "input",
      label: "入力・生成",
      hint: "入力フォームはこれから。いまは説明のみ",
      columns: [
        { key: "step", label: "工程" },
        { key: "status", label: "PWA状態" },
      ],
      rows: [
        { step: "仕入行から古物情報を引く", status: "未実装（デスクトップが正）" },
        { step: "事業者情報の自動挿入", status: "未実装" },
        { step: "PDF/CSV出力", status: "未実装" },
      ],
    },
  ],
};

export const IMAGES_MENU: ThinMenuConfig = {
  title: "画像管理",
  description:
    "デスクトップの「画像管理」「画像登録」に相当する薄い版です。画像アップロードは未接続です。",
  tabs: [
    {
      id: "manage",
      label: "画像管理",
      columns: [
        { key: "sku", label: "SKU" },
        { key: "name", label: "商品名" },
        { key: "images", label: "画像枚数", align: "right" },
        { key: "status", label: "状態" },
      ],
      rows: [
        {
          sku: "250820-FIG-001",
          name: "ダミーフィギュアA",
          images: 4,
          status: "登録済",
        },
        {
          sku: "250821-FIG-002",
          name: "ダミーフィギュアB",
          images: 0,
          status: "未登録",
        },
      ],
      summary: [
        { label: "未登録", value: 1, tone: "warn" },
        { label: "登録済", value: 1, tone: "ok" },
      ],
    },
    {
      id: "register",
      label: "画像登録",
      hint: "ドラッグ登録・メルカリ連携はデスクトップ側",
      columns: [
        { key: "slot", label: "枠" },
        { key: "note", label: "説明" },
      ],
      rows: [
        { slot: "画像1〜6", note: "商品ごとに最大6枚（ダミー表示のみ）" },
        { slot: "確定処理", note: "仕入DBへ反映（PWA未接続）" },
      ],
    },
  ],
};

export const EVIDENCE_MENU: ThinMenuConfig = {
  title: "証憑管理",
  description:
    "デスクトップのレシート・経費・勘定科目に相当する薄い版です。OCRや仕入突合は未接続です。",
  tabs: [
    {
      id: "receipts",
      label: "レシート・領収書・保証書",
      columns: [
        { key: "date", label: "日付" },
        { key: "store", label: "店舗" },
        { key: "amount", label: "金額", align: "right" },
        { key: "match", label: "仕入突合" },
      ],
      rows: [
        {
          date: "2026-08-20",
          store: "ブックオフ玉川",
          amount: 2640,
          match: "未突合",
        },
        {
          date: "2026-08-21",
          store: "ハードオフ川崎",
          amount: 550,
          match: "突合済（ダミー）",
        },
      ],
    },
    {
      id: "expense",
      label: "経費管理",
      columns: [
        { key: "date", label: "日付" },
        { key: "category", label: "科目" },
        { key: "amount", label: "金額", align: "right" },
        { key: "memo", label: "メモ" },
      ],
      rows: [
        {
          date: "2026-08-22",
          category: "交通費",
          amount: 680,
          memo: "ルート移動",
        },
        {
          date: "2026-08-22",
          category: "梱包資材",
          amount: 420,
          memo: "段ボール",
        },
      ],
    },
    {
      id: "accounts",
      label: "勘定科目設定",
      columns: [
        { key: "code", label: "コード" },
        { key: "name", label: "科目名" },
        { key: "type", label: "区分" },
      ],
      rows: [
        { code: "510", name: "仕入高", type: "費用" },
        { code: "720", name: "交通費", type: "費用" },
        { code: "730", name: "梱包資材費", type: "費用" },
      ],
    },
  ],
};

export const ANALYSIS_MENU: ThinMenuConfig = {
  title: "分析",
  description:
    "デスクトップの基本統計・グラフ分析に相当する薄い版です。グラフは数値サマリーで代用しています。",
  tabs: [
    {
      id: "stats",
      label: "基本統計",
      hint: "直近30日のイメージ（ダミー）",
      columns: [
        { key: "metric", label: "指標" },
        { key: "value", label: "値", align: "right" },
        { key: "note", label: "メモ" },
      ],
      rows: [
        { metric: "仕入件数", value: 42, note: "ダミー集計" },
        { metric: "仕入総額", value: "¥86,400", note: "ダミー集計" },
        { metric: "見込み粗利", value: "¥28,200", note: "ダミー集計" },
        { metric: "平均仕入単価", value: "¥2,057", note: "ダミー集計" },
      ],
      summary: [
        { label: "対象期間", value: "30日" },
        { label: "店舗数", value: 8 },
        { label: "粗利率目安", value: "32%", tone: "ok" },
      ],
    },
    {
      id: "stores",
      label: "店舗スコア",
      columns: [
        { key: "store", label: "店舗" },
        { key: "score", label: "スコア", align: "right" },
        { key: "hourly", label: "時給目安", align: "right" },
        { key: "trend", label: "傾向" },
      ],
      rows: [
        {
          store: "ブックオフ玉川",
          score: 82,
          hourly: "¥2,400/h",
          trend: "↑",
        },
        {
          store: "ハードオフ川崎",
          score: 71,
          hourly: "¥1,850/h",
          trend: "→",
        },
        {
          store: "セカンドストリート",
          score: 65,
          hourly: "¥1,620/h",
          trend: "↓",
        },
      ],
    },
  ],
};
