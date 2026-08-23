"use client";

const DUMMY_CSV = `SKU,ASIN,title,number,price,cost,akaji,takane,condition,conditionNote,priceTrace,leadtime,amazon-fee,shipping-price,profit,add-delete
="20250201-B0007RBX52-UM-1650-1",="B0007RBX52",="JVCヘッドホン イヤホン ヘッドセット ヘッドフォン C-P8",="1",="4463",="1650",="2830",="0",="1",="新品未使用です。",="0",="",="809",="0",="2004",=""
="20250201-B000LVNOKQ-UVG-330-1",="B000LVNOKQ",="テスト商品2",="1",="1120",="500",="800",="0",="1",="テスト用商品",="0",="",="200",="0",="420",=""
="20250201-B000RGMGAY-UVG-550-1",="B000RGMGAY",="テスト商品3",="1",="2971",="1500",="2000",="0",="1",="テスト用商品",="0",="",="500",="0",="971",=""
`;

export function DummyRepricerCsvDownload() {
  const handleDownload = () => {
    const blob = new Blob([DUMMY_CSV], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "test_repricer_dummy.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleDownload}
      className="font-medium text-[var(--hirio-accent)] underline"
    >
      ダミーCSVをダウンロード
    </button>
  );
}
