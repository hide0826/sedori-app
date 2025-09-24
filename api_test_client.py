import requests
import os

# --- 設定 ---
API_URL = "http://localhost:8000/repricer/preview"
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'editUploadProduct_FBA.csv') # このファイルの場所を基準にする
OUTPUT_JSON_PATH = os.path.join(os.path.dirname(__file__), 'api_response.json')

def run_test():
    """APIにCSVを送信し、レスポンスをファイルに保存する"""
    try:
        if not os.path.exists(CSV_FILE_PATH):
            print(f"エラー: CSVファイルが見つかりません: {CSV_FILE_PATH}")
            return

        with open(CSV_FILE_PATH, 'rb') as f:
            files = {'file': (os.path.basename(CSV_FILE_PATH), f, 'text/csv')}
            
            print(f"リクエストを送信中: {API_URL}")
            response = requests.post(API_URL, files=files, timeout=60)
            print(f"レスポンス受信: ステータスコード {response.status_code}")

            response.raise_for_status()  # エラーがあれば例外を発生させる

            # レスポンスをJSONとして保存
            with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as f_out:
                f_out.write(response.text)
            
            print(f"成功: レスポンスを {OUTPUT_JSON_PATH} に保存しました。")
            print("--- レスポンスの最初の500文字 ---")
            print(response.text[:500])
            print("---------------------------------")


    except requests.exceptions.RequestException as e:
        print(f"リクエストエラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"エラー詳細: {e.response.text}")
    except Exception as e:
        print(f"予期せぬエラー: {e}")

if __name__ == "__main__":
    run_test()
