/** 価格改定ダミーCSV（改定実行・SP-API改定で共用） */

export const DUMMY_REPRICER_CSV = `SKU,ASIN,title,number,price,cost,akaji,takane,condition,conditionNote,priceTrace,leadtime,amazon-fee,shipping-price,profit,add-delete
="20250201-B0007RBX52-UM-1650-1",="B0007RBX52",="JVCヘッドホン イヤホン ヘッドセット ヘッドフォン C-P8",="1",="4463",="1650",="2830",="0",="1",="新品未使用です。",="0",="",="809",="0",="2004",=""
="20250201-B000LVNOKQ-UVG-330-1",="B000LVNOKQ",="テスト商品2",="1",="1120",="500",="800",="0",="1",="テスト用商品",="0",="",="200",="0",="420",=""
="20250201-B000RGMGAY-UVG-550-1",="B000RGMGAY",="テスト商品3",="1",="2971",="1500",="2000",="0",="1",="テスト用商品",="0",="",="500",="0",="971",=""
`;

export const DUMMY_REPRICER_FILENAME = "test_repricer_dummy.csv";

export function createDummyRepricerFile(): File {
  return new File([DUMMY_REPRICER_CSV], DUMMY_REPRICER_FILENAME, {
    type: "text/csv",
  });
}

export type DummyListingRow = {
  sku: string;
  asin: string;
  title: string;
  price: number;
  cost: number;
  akaji: number;
};

/** 取得後の一覧表示用（CSVの ="" を外した読みやすい形） */
export const DUMMY_LISTINGS: DummyListingRow[] = [
  {
    sku: "20250201-B0007RBX52-UM-1650-1",
    asin: "B0007RBX52",
    title: "JVCヘッドホン イヤホン ヘッドセット ヘッドフォン C-P8",
    price: 4463,
    cost: 1650,
    akaji: 2830,
  },
  {
    sku: "20250201-B000LVNOKQ-UVG-330-1",
    asin: "B000LVNOKQ",
    title: "テスト商品2",
    price: 1120,
    cost: 500,
    akaji: 800,
  },
  {
    sku: "20250201-B000RGMGAY-UVG-550-1",
    asin: "B000RGMGAY",
    title: "テスト商品3",
    price: 2971,
    cost: 1500,
    akaji: 2000,
  },
];
