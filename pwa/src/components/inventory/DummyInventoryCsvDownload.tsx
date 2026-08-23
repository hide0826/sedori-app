"use client";

/** 仕入CSVアップロード用のダミー（日本語列名） */
const DUMMY_CSV = `仕入れ日,コンディション,SKU,ASIN,JAN,商品名,仕入れ個数,仕入れ価格,販売予定価格,見込み利益,損益分岐点,コメント,参考価格,発送方法,仕入れ先,コンディション説明,その他費用,priceTrace
2026-08-20,中古(良い),,B0DUMMY001,4901234567890,ダミーフィギュアA,1,800,1500,400,1000,動作確認済み,1400,宅配,ブックオフ,【動作確認】問題ありません。,0,0
2026-08-21,中古(非常に良い),,B0DUMMY002,4901234567891,ダミーフィギュアB,2,1200,2200,600,1600,,2100,宅配,ハードオフ,,0,0
`;

export function DummyInventoryCsvDownload() {
  const handleClick = () => {
    const blob = new Blob([DUMMY_CSV], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "test_inventory_dummy.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="font-medium text-[var(--hirio-accent)] underline underline-offset-2 hover:opacity-80"
    >
      ダミー仕入CSVをダウンロード
    </button>
  );
}
