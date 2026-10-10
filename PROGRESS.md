# sedori-app 進捗（Cursor 向け）

本体デスクトップ（PySide6）＋事務PWA の詳細。HIRIO 全体の地図は [`C:\HIRIO\PROGRESS.md`](../../PROGRESS.md)。

更新日: 2026-10-08（情報撮影・最小化／東京都）

---

## いまの状態

**2026-10-08（情報撮影・最小化／受取都道府県）:** 情報撮影が終わると、使っていたChromeを最小化する。拡張 **1.0.6**。ネット仕入で受取都道府県が空の行は「東京都」を入れる（行の編集を開いたときと、DB保存のとき）。設定画面は未作成。値の置き場所は `online_purchase/receive_prefecture`（空なら東京都）。反映は **HIRIO 再起動**＋ chrome://extensions で拡張再読み込み。

**2026-10-08（仕入一覧スナップ）:** 仕入データ／ネット仕入の補助ボタンに「スナップ保存」「スナップ呼出」。いまの一覧を名前つきで保存し、あとから丸ごと置き換え、またはうしろへ追加できる。タブごとに別保存（混ざらない）。ストック保存（出品まとめ用）とは別。反映には **HIRIO 再起動**。

**2026-10-07（情報撮影・ユーザー名）:** 取引IDは取れるがユーザー名が空になる件を修正。拡張が取引画面の DOM から出品者名を送る。OCRは「よう本人確認済」のように名前とバッジが同一行でも切り出す。拡張 **1.0.5**。反映は **HIRIO 再起動**＋ chrome://extensions で拡張再読み込み。

**2026-10-07（情報撮影・最大化／速度）:** 真正の全画面（F11相当）はやめ、ウィンドウの**最大化**（タイトルバー等の外周が残る）で撮る。ページ待ち・ショット間待ちを少し短縮。反映は拡張の再読み込み。

**2026-10-07（CSV取込・追記）:** 仕入データ／ネット仕入の「CSV取込」は、既存一覧があるとき消さず末尾へ追記。ダイアログでCSVを複数選択可。「ルート箱からCSV取込」も追記。入れ直すときは先に「クリア」。反映には **HIRIO 再起動**。

**2026-10-07（詳細説明・カスタム無制限）:** 仕入管理「コンディション説明＞詳細説明」で、上段欠品3種は固定のまま、下段カスタムを「行を追加／選択行を削除」で件数無制限に増減できる。行の編集・単品仕入の「欠品・詳細」チェックも保存件数に追従。反映には **HIRIO 再起動**。

**2026-10-07（ネット仕入・情報撮影）:** 撮影前に画像読み込み待ちを追加。ウィンドウが全画面でなければ一時的に全画面にして撮る（終了後は元に戻す）。拡張機能 **1.0.3** を chrome://extensions で再読み込み。反映には **HIRIO 再起動**＋拡張の再読み込み。

**2026-10-07（ネット仕入・情報撮影・配置）:** 「情報撮影」をメインから「行の編集」へ移動。既存証憑は上書きしない（空枠だけ保存）。

**2026-10-07（ネット仕入・行の編集）:** 「出品URL」を「仕入れ日」の直前へ移動（必須入力を上に）。表の列順は変更なし。反映には **HIRIO 再起動**。

**2026-10-07（画像管理・1枚目チェック一括切替）:** 左のJANグループに「1枚目チェックをすべてON／OFF」ボタンを追加。各グループ1枚目の登録可否チェックを1クリックで一括切替。反映には **HIRIO 再起動**。

**2026-10-07（画像管理・ASIN紐付け）:** 仕入DBに JAN が無くても ASIN（または SKU）で画像を紐付けできる。画像DBに `asin` 列を追加。左ツリーは ASIN グループを `ASIN: XXXX` と表示。ルートWebの ASIN のみ写真も画像DBへ種まき。反映には **HIRIO 再起動**（ルート撮影も使うならルートWebも再起動）。

**2026-10-06（ルート地図・件数表示／名前変更）:** 左パネルに「ルート数／所属店舗数／未所属店舗数」を表示。「ルート名変更」ボタンで編集中ルートの名前を変更可能。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・線ホバー／選択連動）:** ルート線にマウスを乗せると「ルート名（○店）」とダブルクリック案内を表示。線をダブルクリックすると左のルート一覧でそのルートが青ハイライトされ、見える位置までスクロール。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・範囲囲み安定化）:** 「範囲で囲む」で点線がすぐ消え／「認識できませんでした」になる不具合を修正。マウス追跡強化、点列は title 同期渡し＋`JSON.stringify` バックアップ（`runJavaScript` のオブジェクト変換失敗対策）、小さすぎ判定緩和、店舗0件時も囲みを残す。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・フリーハンド範囲登録）:** 「範囲で囲む」でフリーハンド囲み→内側の店を抽出（併設はまとめて）→スタート／ゴールをクリック→近傍順で仮並び登録。微調整は訪問順序選択。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・ルート新規登録）:** ルートエリアに「ルート新規登録」。名前入力後、地図クリックで店舗を所属登録（クリック順＝訪問順）。他ルートの店は移動で外し、未所属も登録可。再クリックで未所属へ。「登録終了」でモード終了。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・DB削除後もズーム維持）:** 地図ポップアップの「DBから削除」「個別削除」のあと、地図が全体表示へ戻らない（いま見ていた位置・ズームのまま）。反映には **HIRIO 再起動**。

**2026-10-06（ルート地図・店舗エリアからルート外し）:** 左の店舗リストで店を選び「ルートから外す」（右クリック／Deleteキーも可）で、編集中ルートのグループから外せる。店舗自体はDBに残る。反映には **HIRIO 再起動**。

**2026-10-05（ルート地図・併設の個別削除）:** ハードオフ系ピンのポップアップで、併設一覧の各店ごとに「削除」できる。誤登録の1店だけDBから消せる（他の併設は残る）。まとめて消すときは「全店をDBから削除」。反映には **HIRIO 再起動**。

**2026-10-05（ルート地図・訪問順選択で未選択をスキップ）:** 「地図上で訪問順序選択」でクリックしなかったルート登録店は、店舗エリアのチェックが**自動でOFF**（スキップ＝地図グレー＋最後尾から点線）。選んだ店はチェックONのまま先頭に並ぶ。反映には **HIRIO 再起動**。

**2026-10-05（ルート地図・地図からルート選択／解除）:** 店舗ピンまたはルート線の**ダブルクリック**で編集ルートを選択（左パネルのルート名ダブルクリックと同じ）。「ルート選択解除」は編集選択だけ外し、**地図の位置・ズームはそのまま**（全体図へ自動ズームしない。初回タブ表示時のみ全体フィット）。反映には **HIRIO 再起動**。

**2026-10-05（ルート地図・併設ピン統合／訪問順選択）:** 別ルートでも同一付近の HA/HO/OF は地図上で1ピンにまとめる（例: 船橋習志野台の HA-11+HO と HA-60）。「地図上で訪問順序選択」中は**編集中ルートの既存ラインだけ消し**、クリック順の線だけ伸ばす（他ルートの線は残す）。反映には **HIRIO 再起動**。

**2026-10-05（ルート地図・ハードオフ併設確認）:** 店舗マスタ「ルート地図」のハードオフ系ピンに、(1) Google Places で未登録の併設（HA/HO/OF）を自動検索、(2) 候補からそのまま併設店舗登録、(3) 「併設確認済み」チェック（`stores.collocation_checked`）、(4) ピン上の緑✓と凡例表示を追加。未確認かつ不足ブランドがあるピンを開くと自動検索（セッションキャッシュあり）。手動「併設を自動確認」でも再検索可。反映には **HIRIO 再起動**。

**2026-10-05（TWSバッテリー検品）:** ルートWeb（`:8792`）に `C:\HIRIO\tws-battery-check` を `/tws` で静的配信。履歴APIは `/api/tws-battery/*`（SQLite は `tws-battery-check/data/inspections.db`）。撮影・巡回トップにリンク追加。スマホは `https://houseserver.tail0a340c.ts.net/tws/`。詳細は [`tws-battery-check/PROGRESS.md`](../../tws-battery-check/PROGRESS.md)。反映はルートWeb再起動（実施済み）。

**2026-10-04（ルート地図・周回編集／WEBテンプレ）:** 訪問チェックOFF＝行かない（地図iconグレー＋最後尾から薄い点線）。状態は `stores.template_include`（ルート登録の出力チェックと同義）。店舗選択でicon拡大、編集中ルートにスタート／ゴール。訪問順序反転。地図上で訪問順序選択（クリックで順に接続、再クリック解除、戻る／進む／保存）。ルート選択解除で全体マップ。店舗エリアから **WEBテンプレート作成**（最大化可・左右分割・開いた時点でGoogleマップ表示・画面内で訪問順反転可・設定の Maps APIキーで Embed）。反映には **HIRIO 再起動**。

**2026-10-04（ルート地図・左パネル／訪問順）:** 店舗マスタ「ルート地図」の左をダークテーマ（白文字）に統一。ルート一覧・店舗（編集中）・タグ絞り込みを CollapsibleSection＋縦スプリッタにし、畳むとヘッダー高さだけになり余りを他パネルへ配分。左右幅・左3段の高さはドラッグ変更し `QSettings` に保存（畳み状態も記憶）。チェックは枠クリックのみ表示オン／オフ、ルート名ダブルクリックで店舗リスト表示＋地図 fitBounds。店舗リストをドラッグ並べ替え→「訪問順序保存」で `stores.display_order` と最新 `route_summaries` の `store_visit_details.visit_order` を更新し、地図の線順も再描画。反映には **HIRIO 再起動**。

**2026-10-04（店舗マスタ・テキスト貼り付け）:** 店舗一覧の操作に「テキスト貼り付け」を追加。店名を1行ずつ貼ると CSV（Takeout）インポートと同じ処理で未登録店を追加（Mapsで住所・電話・座標、店舗コード自動採番、重複スキップ、HA/HO/OF併設は同ルートへ）。併設のホビーオフ等がハードオフと住所・電話が同じでも別店舗になるよう重複判定を修正。反映には **HIRIO 再起動**。足りないホビーオフは再貼り付けで追加できる（既存ハードオフはスキップ）。

**2026-10-03（巡回Web・店舗備考＋自動保存）:** 撮影・巡回の各店舗カードに、IN/OUT・仕入点数の下へ「備考」を追加。Webテンプレート作成時に店舗マスタ（店舗一覧）の備考を `route.json` の `stores[].notes` として載せ、画面に表示する。スマホで備考を変えて保存（自動保存含む）すると、店舗マスタ `stores.notes`（と custom_fields.notes）も上書き同期。入力フィールドは debounce 約0.7秒で自動 PUT（画面は再描画せずフォーカス維持）。反映には **ルートWeb（:8792）の再起動**。

**2026-10-03（ネット仕入箱）:** 店舗の仕入帳ルートとは別に、ネット仕入用の日付箱を作る（`仕入CSV`／`商品画像`／`証憑スクショ`）。`box_kind=online`・`route_code=NET` の `route.json` を書き、route_web に登録する。ネット仕入の **DB保存** 後に撮影候補（`photo_candidates.json`）を箱へ書き、スマホは既存 https（`https://houseserver.tail0a340c.ts.net/`）の商品撮影画面で撮る（ホームページにネット箱セクション）。証憑専用ボタンは付けない。CSV取込は `仕入CSV/` 内の **任意 `*.csv`**（`StockList_*.csv` 以外のアマサーチ出力も可）。

**2026-10-03（SKU全文編集・即反映）:** 仕入行の編集で SKU 全体を直せる（販売済みはロック）。反映時に仕入DB・商品DB・古物台帳の SKU を同時更新。SKUが変わったときは仕入一覧を `force_full` で再描画し、古物台帳タブも開いていれば再読込（再起動不要）。反映には **一度 HIRIO（と必要ならルートWeb）を再起動**してこのコードを載せる。

**2026-09-27（商品撮影）:** 新品などで写真が不要な商品は、リストを長押しして「画像不要にしますか？」ではいを選ぶと、撮影済みへ「画像不要」バッジ付きで移る。このルートの商品が残らなければ、撮影は終わり。撮影済みの画像不要をタップすると、リストに戻せる。反映にはルートWebの再起動。

**2026-09-26（商品撮影）:** JAN付きの写真は、撮影終了前でも保存と同時に画像DBへ書く。すでに撮った分も画像DBへ入れた。https は Tailscale Serve で有効。スマホは Tailscale をオンにして `https://houseserver.tail0a340c.ts.net/` を開くと、カメラを開いたまま続けて撮れる。縦持ちのまま、保存される写真は中央の横長（4:3）だけ。`http://houseserver:8792` は1枚ずつ。操作は Windows ユーザー hide に戻した。

**2026-09-26（商品撮影・画面）:** 候補は仕入DBの最新スナップショット。撮影終了は商品を選ぶと押せる（写真が1枚あると緑）。押すと選択が外れ、その商品は「撮影済み」ページへ移り、選ぶ一覧からは消える。撮影済みをタップすると「再撮影しますか？」と聞き、はいなら写真を消して選び直す画面に戻る。選んだ商品のボタンは緑になる。JANが仕入DBに無い商品は ASIN で写真を紐付ける。反映にはルートWebの再起動。

**2026-09-26（Notion）:** 仕様書ページへの追記はやめる。開くだけでトークン消費が大きい。方針と進捗は `C:\HIRIO\PROGRESS.md` とこのファイル、`docs/specs/` に書く。

**2026-09-26（整理）:** 枝 `feature/sp-api` に push 済み。`244a26a` 欠品チェック時は詳細説明の文だけ。`6d423f8` ルート保険（Excel と空の仕入CSVだけ。仕入帳は上げない）。手元の残りは、HIRIO を一度閉じて開くこと、ドライブの同期を `D:\せどり総合\店舗せどり仕入リスト入れ\ルート保険` だけにすること。ネット仕入の SKU に `MERCARI` や `YAAU` を入れるときは、設定のフリマコードで名称を仕入先（メルカリ、ヤフオク）に合わせ、接頭辞にその文字を書く。

**2026-09-25（欠品チェック時の説明）:** 行の編集で「取説欠品」などにチェックを入れて「コンディション説明呼び出し」を押すと、良い・非常に良い・可のテンプレートは足さない。詳細説明に保存した文だけを入れる。チェックが無いときは、これまでどおりコンディションのテンプレート。反映には HIRIO を一度閉じてもう一度開く。

**2026-09-25（ルート保険）:** 仕入帳はドライブに上げない（約23GB）。Webテンプレ作成時に Excel と空の `仕入CSV` だけ `D:\せどり総合\店舗せどり仕入リスト入れ\ルート保険\日付＋ルート名` へコピーする。ドライブアプリはこのフォルダだけミラーリングする。帰宅後のルート箱取込は、仕入帳の箱を選ぶとルート保険側の新しい CSV と Excel を読む。反映には HIRIO を一度閉じてもう一度開く。rclone は送らない。

**2026-09-25（行の編集のユーザー名）:** OKを押すと、画像がある行は OCR がもう一度走り、その完了通知がユーザー名を上書きしていた。`row_edit_dialog.py` の OK では通知を切ってから読み、空欄だけ埋める。配送表示に「サイズ」「厚さ」「重さ」「kg以内」「cm以内」を追加し、「サイズ:厚さ7cm以内重さ2kg以内」はユーザー名にしない。反映には HIRIO を一度閉じてもう一度開く。

**2026-09-25（夜の再起動が戻らない）:** 9/25 3:00 の再起動は記録上実行済みだが、朝から本体が落ちたまま。`nightly_restart_done=2026-09-25`。待ちの PowerShell が HIRIO と同じコンソールに付いていて、終了で一緒に消えていた。`schedule_relaunch_after_exit` を `DETACHED_PROCESS` で切り離し、`python/desktop/logs/nightly_restart.log` に結果を残す。反映には、いま開いている HIRIO を一度閉じてもう一度開く。バックアップ先 `Z:\HIRIObackup` は現在見えていない（最終成功は 9/23 16:31）。

**2026-09-23（情報撮影）:** ネット仕入の「情報撮影」は、いま開いているログイン済みChromeでメルカリを3枚撮る。拡張 `python/desktop/mercari_capture_extension`（表示名「HIRIO メルカリ撮影」1.0.2）を一度読み込む。撮影はゆっくり。サムネはダブルクリックで拡大。ユーザー名は「ゆうパケットプラスでお届け」などを飛ばす。行の編集で直したユーザー名・取引ID・出品URLは、OKを押しても空欄のときだけ画像の読み取りで埋める。反映には HIRIO 再起動。拡張の中身を変えたあとは chrome://extensions で再読み込み。ヤフオクは未対応。

**2026-09-23（仕入チャネル）:** ネット仕入の仕入チャネルは、CSVの「仕入れ先」から入れる。コメントは見ない。反映には HIRIO 再起動。

**2026-09-23（夜の再起動）:** データバックアップで「毎日、夜中に一度終了して起動し直す」を追加。初期値は毎日 03:00（その時刻から3時間、PCが起きていれば1回）。終了時バックアップがオンなら、閉じるときに ZIP を作ってから起動し直す。反映には HIRIO 再起動。

**2026-09-23（ストック）:** 仕入データとネット仕入の「統合保存／統合読込」を「ストック保存／ストック読込」に変更。保存はルート名＋仕入一覧＋ルート情報。読込は商品を選んで、いま開いている一覧のうしろに追加する（ルート情報は上書きしない）。反映には HIRIO 再起動。

**2026-09-23（ネット仕入のCSV）:** ネット仕入タブに「ルート箱からCSV取込」。仕入CSVだけ読み、ルート情報・画像・レシートは開かない。店舗の仕入データタブの「ルート箱から取込」はそのまま。反映には HIRIO 再起動。

**2026-09-23（ルート箱取込）:** 仕入データの「ルート箱から取込」でルート情報も開く。時刻・メモ・高速代・仕入点数がある `route.json` を優先。店名だけの JSON や空の JSON は Excel のルートテンプレを開く。反映には HIRIO 再起動が必要。

**2026-09-23（ルート一覧の番人）:** `:8792` が落ちたら `python/route_web/watch.ps1` が約15秒で起動し直す。タスク `HIRIO_route_web`（ログオン時・起動2分後・5分おき）。再起動後は watcher の `HIRIO_boot_recover` もこの番人を起こす。`houseserver` は IPv6 が先に返るので、待ち受けは IPv4 と IPv6 の両方。ホーム画面アイコンは `static/icon.png`（表示名「ルート巡回」）。ログ `python/route_web/logs/route_web_watchdog.log`。

**2026-09-23（先読み・撮影分離）:** 巡回Webは時刻とレシートだけ。商品撮影は `/route/{web_id}/photos`（仕入保存後）。「事前処理」はレシートをリネームせずOCRし、2回目は読み直さない。ルート箱取込は、入力がある `route.json` を Excel より優先する。確定した商品JANは画像DBに先に書き、スキャンはバーコードを読まない。サンドボックス `20260919鎌倉ルートサンドボックス` で、本番鎌倉ルートをコピーして確認（本番フォルダは未変更）。仕入の保存とプライスター送信は自動テストしていない。

**2026-09-22（rclone安定化）:** Drive は Google Drive デスクトップの常時同期不要。Webテンプレ作成後に **バックグラウンドで `rclone copy`**（mkdir 省略・フォルダは copy が作る）。GUI から rclone を探す（WinGet Links／フルパス）。地図埋め込み失敗時は「ブラウザで開く」案内。ホワイトアウト対策済。`config/rclone_route_drive.json` はローカルのみ（gitignore）。

**2026-09-22（現場ルートWeb）:** CSV は Drive 直送が正。Webテンプレで **Excel 同時生成**＋**rclone で Drive 上に箱作成**（未設定時スキップ）。1.5b 見送り。枝 `feature/sp-api`。仕様 [`field_route_web_spec.md`](docs/specs/field_route_web_spec.md)。

**2026-09-22（証憑OCR）:** ミニPCで全件OCRを実機確認。一覧に10件前後が載り、BOOK OFF 等は日付・合計まで入る。Tesseract は動作。日本語レシートは精度が低い行あり（Gemini API 設定で改善可）。一括マッチング以降はユーザー確認済み。

**2026-09-21 夜（証憑OCR）:** 全件OCRが処理せず完了していた。ミニPCに Tesseract 本体と日本語データが無く、失敗を黙って飛ばしていた。導入して開始前点検を入れた。

**方針転換（2026-09-21）:** このリポジトリの**実装をミニPCに置き、開発も日常運用もここで行う。**  
理由: `C:\HIRIO` にある watcher / store-cam / judgment / shared などの資産を、同じワークスペースで使いながらシームレスに進めるため。全体Web化の完了は待たない。

**2026-09-21 夜（画像管理）:** スキャンのJAN照合・複数選択・仕入DB候補紐付けを直した。**中央で選んだ画像だけ**別商品へ付け替える。反映には HIRIO 再起動が必要。

- ブランチ: **`feature/sp-api`**（旧作業枝 `feature/route-web-template` はマージ済・同コミット）
- 起動: `start_hirio.bat` または `.venv\Scripts\python.exe python\desktop\main.py`
- ルート時刻Web: 番人 `python\route_web\watch.ps1`（`:8792`。落ちたら起動し直す）。手動は `start_route_web.bat`
- Python: 3.13.15 / venv はこのマシンで作り直し済み
- FastAPI: デスクトップ起動時に自動起動（失敗しても仕入画面は動く）

---

---

---

## 2026-10-08 情報撮影後の最小化と受取都道府県

### 動き

1. 情報撮影の全ジョブが終わったあと（失敗で終わったときも含む）、撮影に使った Chrome を最小化する
2. ネット仕入の「行の編集」で受取都道府県が空なら「東京都」を入れる（手入力済みは上書きしない）
3. DB保存のときも、ネット仕入で空なら同じ既定を書く
4. 設定欄はまだ無い。あとで `online_purchase/receive_prefecture` に値を書けばそちらを使う

### 追加・変更

| 何 | 場所 |
|----|------|
| 最小化 | `mercari_capture_extension/background.js`（1.0.6） |
| 既定の都道府県 | `utils/settings_helper.py` の `get_default_receive_prefecture` |
| 行の編集 | `ui/inventory/row_edit_dialog.py` |
| DB保存 | `ui/inventory/persistence_mixin.py` |

### 確認（実機）

1. HIRIO 再起動
2. chrome://extensions で「HIRIO メルカリ撮影」を再読み込み（1.0.6）
3. 情報撮影のあと Chrome が最小化されるか
4. 行の編集の受取都道府県が空なら東京都になるか

---

## 2026-10-08 仕入一覧の作業スナップショット

CSVを何本か足した作業中の一覧を、アプリを閉じても戻せるようにする。既存の「ストック保存」は出品をまとめる用なので、そのまま残す。

### 動き

1. 仕入データ／ネット仕入の「スナップ保存」→ 名前（初期値は日時＋件数）→ いまの一覧を保存
2. 「スナップ呼出」→ 一覧から選ぶ → いまの一覧が空ならそのまま表示
3. すでに行があるときは「置き換える」か「うしろに追加」
4. 仕入データとネット仕入は別々（片方の呼出に、もう片方は出ない）
5. ダイアログの「削除」で不要なスナップを消せる。古いものは40件を超えると自動で捨てる

### 追加・変更

| 何 | 場所 |
|----|------|
| 保存先 | `python/desktop/data/inventory_work_snapshots/`（Git対象外） |
| 保存処理 | `python/desktop/services/inventory_work_snapshot.py` |
| 呼出ダイアログ | `python/desktop/ui/inventory/work_snapshot_dialog.py` |
| ボタンと連携 | `widget.py` / `persistence_mixin.py` |
| 試験 | `python/desktop/tests/test_inventory_work_snapshot.py` |

### 確認（実機）

1. HIRIO 再起動
2. ネット仕入で一覧がある状態で「スナップ保存」
3. オールクリアしたあと「スナップ呼出」で同じ行が戻るか
4. 仕入データタブの呼出一覧に、ネット仕入のスナップが出ないか

---

## 2026-10-07 情報撮影・ユーザー名（拡張 1.0.5）

取引IDは入るがユーザー名が空になる。最大化で画面が少し低く、出品者欄がスクショ外になる／OCRで「よう本人確認済」とくっつく、が主因。

### 動き

1. 取引画面撮影前に DOM から出品者名を取得し、結果 JSON の `seller_name` で HIRIO へ送る
2. HIRIO は DOM 名を優先し、無ければ OCR
3. OCR はスキップ文言を除いた残りを名前にする（同一行の本人確認バッジ対策）
4. 「本人確認済」の直前行からも候補を取る

### 追加・変更

| 何 | 場所 |
|----|------|
| DOM取得・結果送信 | `mercari_capture_extension/background.js` |
| 版 1.0.5 | `mercari_capture_extension/manifest.json` |
| hint 反映 | `ui/inventory/mercari_capture_mixin.py` |
| OCR切り出し強化 | `services/flea_market_evidence_ocr.py` |
| 試験 | `tests/test_flea_market_evidence_ocr.py` |

### 確認（実機）

1. HIRIO 再起動
2. chrome://extensions → 「HIRIO メルカリ撮影」再読み込み（1.0.5）
3. 行の編集で情報撮影 → ユーザー名が入るか

---

## 2026-10-07 情報撮影・最大化＋待ち短縮（拡張 1.0.4）

真正の全画面だと外周が消えて操作感が重い、という要望に合わせる。

### 動き

1. 撮影時は Chrome を **最大化**（`state: maximized`）。全画面（`fullscreen`）にはしない
2. もともと全画面だった場合も最大化へ戻してから撮る
3. 終了後は撮影前のウィンドウ状態へ戻す
4. ページ表示待ち・画像待ち・ショット間待ちを少し短縮（白飛び対策は残す）

### 追加・変更

| 何 | 場所 |
|----|------|
| 最大化・待ち時間 | `python/desktop/mercari_capture_extension/background.js` |
| 版（当時） | `manifest.json`（現在は 1.0.5） |

### 確認（実機）

1. 拡張再読み込み後、タイトルバーが残った最大化になるか
2. 3枚撮れるか／以前より少し速いか

---

## 2026-10-07 CSV取込・既存へ追記（複数選択）

これまで CSV 取込のたびに一覧を差し替えていたため、続けて別CSVを読むと前のデータが消えていた。

### 動き

1. 「CSV取込」でファイルを複数選べる
2. すでに一覧があるときは末尾へ追記（仕入データ／ネット仕入とも）
3. 「ルート箱からCSV取込」も同様に追記
4. 消して入れ直すときは先に「クリア」

### 追加・変更

| 何 | 場所 |
|----|------|
| 複数選択＋追記 | `python/desktop/ui/inventory/csv_import_mixin.py` |
| ツールチップ | `python/desktop/ui/inventory/widget.py` |

### 確認（実機）

1. HIRIO 再起動
2. CSV取込 → 別CSVをもう一度取込 → 行が足し算になっているか
3. ダイアログで2ファイル同時選択 → 両方入るか

---

## 2026-10-07 詳細説明タブ・カスタム無制限

これまでカスタムは `custom1`〜`custom3` の3件固定だった。よく使う定番説明を増やしたい要望に合わせ、件数上限を外した。

### 動き

1. 仕入管理 → コンディション説明 → **詳細説明**
2. 上段3行（取説欠品／内箱欠品／取説・内箱欠品）は名称固定のまま
3. **行を追加** でカスタム行を末尾に追加（`custom4`, `custom5`… 件数上限なし）
4. カスタム行を選んで **選択行を削除**（上段3種は削除不可）
5. **保存** で `missing_keywords.json` の `keywords` / `custom_labels` に反映
6. 行の編集・単品仕入の「欠品・詳細」チェックは、保存されたカスタム件数・名称に合わせて表示

### 追加・変更

| 何 | 場所 |
|----|------|
| 行追加／削除UI・動的行 | `python/desktop/ui/condition_template_widget.py` |
| customN ヘルパー／呼び出し | `python/desktop/ui/inventory/support.py` |
| 行編集の動的チェック | `python/desktop/ui/inventory/row_edit_dialog.py` |
| 単品仕入の動的チェック | `python/desktop/ui/inventory/single_purchase_dialog.py` |
| 試験 | `python/desktop/tests/test_custom_detail_templates.py` |

### 確認（実機）

1. HIRIO 再起動
2. 詳細説明で「行を追加」→名称・コメント入力→保存
3. 行の編集を開き、追加した名称のチェックが出るか
4. チェックして「コンディション説明呼び出し」で文が入るか

### 次の一手

1. 上記の実機確認（再起動後）

---

## 2026-10-06 ルート地図・フリーハンド範囲登録（＋安定化）

歪な範囲をペンで囲んで、まとめてルートに入れる。

### 動き

1. 編集中ルート（またはルート新規登録中）で「範囲で囲む」ON
2. ドラッグで囲む → 内側のピンを拾う（併設はメンバー全部）
3. スタート地点をクリック → ゴール地点をクリック
4. スタートから近い順に仮並び（ゴールは最後）→ 所属移動＋訪問順保存
5. 微調整は「地図上で訪問順序選択」

### 不具合と修正（点線がすぐ消える）

- **症状:** 囲んでも点線がすぐ消え、スタート案内が出ず、0件ルートだけ残る
- **原因候補:** マウス追跡不足／長い `document.title` が切れて commit 失敗／描画中のフルHTML再読込
- **修正:** Leaflet `mousemove`/`mouseup`＋document バックアップ、点列は `__HIRIO_LASSO_PENDING` 経由、小さすぎ判定緩和、店舗0件時も囲みを残す、描画中のフル再読込回避

### 追加・変更

| 何 | 場所 |
|----|------|
| フリーハンド描画 | `route_map_widget.py`（Leaflet / `HIRIO_LASSO` / `__HIRIO_LASSO_PENDING`） |
| 点内判定・近傍順 | 同上（`_point_in_polygon` / `_order_groups_nearest_neighbor`） |
| テスト | `test_route_map_collocation_register.py` |

### 確認（実機）

1. HIRIO 再起動
2. ルート編集中に「範囲で囲む」→ **ゆっくり大きく**囲む → 「スタート地点をクリック」と出るか
3. スタート／ゴール → 店舗が並ぶか
4. 併設ピンがまとめて入るか

### 次の一手

1. 上記の実機確認（再起動後）

---

## 2026-10-06 ルート地図・ルート新規登録（地図クリック編成）

2本のルート＋未所属を、地図上でクリックして3本などに組み直せるようにする。

### 動き

1. ルートエリア「ルート新規登録」→ ルート名入力 → `routes` に追加（R###）
2. 地図の店をクリック → そのルートへ所属移動（他ルートからは外す）＋訪問順に追加
3. 未所属も同じ操作で登録
4. 再クリック → 未所属へ戻す（元ルートへは戻さない）
5. 「登録終了」でモード終了（ズーム維持）

### 追加・変更

| 何 | 場所 |
|----|------|
| 新規登録ボタン／登録終了 | `python/desktop/ui/store_master/route_map_widget.py` |
| クリック編成モード | 同上（`_build_route_mode` / `move_store_to_route`） |

### 確認（実機）

1. HIRIO 再起動
2. 「ルート新規登録」→ 名前 → 地図で数店クリック → 店舗エリアに並ぶか
3. 他ルートの店をクリック → 元ルートから外れるか
4. 「登録終了」後もズームが動かないか

### 次の一手

1. 上記の実機確認

---

## 2026-10-06 ルート地図・DB削除後も地図ズームを維持

近くの店を続けて直しているときに、削除のたびに全体図へ飛ばないようにする。

### 動き

1. 「DBから削除」または併設の個別「削除」→ 確認 → 削除
2. 地図の中心・ズームはそのまま（全体表示へ自動で戻らない）

### 追加・変更

| 何 | 場所 |
|----|------|
| 削除後の fit_all をやめる | `python/desktop/ui/store_master/route_map_widget.py` |

### 確認（実機）

1. HIRIO 再起動
2. 地図をあるルート付近に拡大したまま、未所属店を「DBから削除」
3. 視点が動かず、その付近のままか

### 次の一手

1. 上記の実機確認

---

## 2026-10-06 ルート地図・店舗エリアからルート（グループ）外し

店舗リストから、編集中ルートに入れたくない店を外せるようにする。

### 動き

1. ルートをダブルクリックして店舗エリアを開く
2. 店を選んで「ルートから外す」（右クリックメニュー／Deleteキーでも可）
3. 確認後、そのルートのグループから外れる（DBの店舗データは残る）

### 追加・変更

| 何 | 場所 |
|----|------|
| ルートから外すボタン／右クリック／Delete | `python/desktop/ui/store_master/route_map_widget.py` |

### 確認（実機）

1. HIRIO 再起動
2. 店舗エリアで店を選び「ルートから外す」→ リストと地図から消えるか
3. 店舗一覧（マスタ）には店が残っているか

### 次の一手

1. 上記の実機確認

---

## 2026-10-05 ルート地図・併設店舗の個別削除

ハードオフ系の併設ピンで、実在しない1店だけを地図ポップアップから消せるようにする。

### 動き

1. 併設が2店以上のピンを開く → 各店の横に「削除」
2. 「削除」→ 確認ダイアログ → その1店だけDB削除（他の併設は残る）
3. まとめて消すときは「全店をDBから削除」

### 追加・変更

| 何 | 場所 |
|----|------|
| 併設一覧＋個別削除UI | `python/desktop/ui/store_master/route_map_widget.py` |
| `members` 配列（id/code/name） | 同上（`_member_entry_from_store`） |
| `delete_one` アクション | 同上 |

### 確認（実機）

1. HIRIO 再起動
2. H3ピン（例: コーナン港北センター南）を開き、ハードオフだけ「削除」
3. ホビーオフ／オフハウスが残り、ピンが H2 になるか

### 次の一手

1. 上記の実機確認

---

## 2026-10-05 ルート地図・訪問順選択で未選択店を自動スキップ

地図クリックで周回順を決めるとき、選ばなかった店のチェックを手動で外す手間をなくす。

### 動き

1. 「地図上で訪問順序選択」でクリックした店 → 先頭に並び・チェックON（行く）
2. ルートに登録されていてもクリックしなかった店 → 末尾に残り・チェックOFF（スキップ）
3. 保存時はそのチェック状態が `template_include` に反映される

### 追加・変更

| 何 | 場所 |
|----|------|
| 未選択＝チェックOFF | `python/desktop/ui/store_master/route_map_widget.py`（`_rows_for_pick_order`） |
| テスト | `python/desktop/tests/test_route_map_collocation_register.py` |

### 確認（実機）

1. HIRIO 再起動
2. ルートを編集対象にして「地図上で訪問順序選択」
3. 一部の店だけクリック → 未選択店のチェックがOFFになり、地図でグレー／点線になるか

### 次の一手

1. 上記の実機確認

---

## 2026-10-05 ルート地図・地図ダブルクリック選択と選択解除時のズーム維持

地図上からルートを選びやすくし、選択解除で視点が飛ばないようにする。

### 動き

1. 店舗ピン／ルート線をダブルクリック → 編集ルート選択＋店舗一覧＋地図拡大（左パネルと同じ）
2. 「ルート選択解除」→ 編集選択だけ解除。地図の中心・ズームは維持
3. 訪問順序選択中はダブルクリックでのルート切替なし（誤操作防止）

### 追加・変更

| 何 | 場所 |
|----|------|
| ピン／線のダブルクリック | `python/desktop/ui/store_master/route_map_widget.py` |
| 選択解除の fit_all 制御 | 同上（`clear_editing_route_focus`） |

### 確認（実機）

1. HIRIO 再起動
2. 地図のピンまたは線をダブルクリックしてルートが選ばれるか
3. 「ルート選択解除」で画面位置が動かないか

### 次の一手

1. 上記の実機確認

---

## 2026-10-05 ルート地図・クロスルート併設ピン統合と訪問順選択時の線消し

別ルートの同一地点ハードオフ系が H1/H2 に分裂しないようにし、訪問順クリック選択中は編集ルートの線だけ消す。

### 動き

1. 表示中の複数ルートで近接（既定80m）の HA/HO/OF ピンを1つに合流（片方は線用スタブ）
2. 「地図上で訪問順序選択」ON 時: 編集中ルートの既存周回線を非表示。クリックした順だけ線が伸びる
3. 他ルートの線・スキップ点線はそのまま

### 追加・変更

| 何 | 場所 |
|----|------|
| クロスルート併設ピン統合 | `python/desktop/ui/store_master/route_map_widget.py`（`_merge_cross_route_hardoff_markers`） |
| 訪問順選択時の線制御 | 同上（Leaflet `editing_route_code`） |
| テスト | `python/desktop/tests/test_route_map_collocation_register.py` |

### 確認（実機）

1. HIRIO 再起動
2. 船橋習志野台付近で HA-11/HO と HA-60 が1ピン（H3）になるか
3. ルートを編集対象にして「地図上で訪問順序選択」ON → そのルートの線だけ消え、他ルートの線が残るか

### 次の一手

1. 上記の実機確認

---

## 2026-10-05 ルート地図・ハードオフ併設自動確認と確認済み

ハードオフ系ピンで、近くの未登録併設を Google で探し、確認済みを地図上一目で分かるようにする。

### 動き

1. ハードオフ系ピンを開く → 「併設確認済み」チェックと「併設を自動確認」ボタン
2. 未確認かつ HA/HO/OF が不足しているとき、ピンオープンで Places 近傍検索（150m）を1回実行（セッションキャッシュ）
3. 候補の「登録」→ 既存の併設店舗登録ダイアログへ店名・住所・電話・座標をプリフィルして DB 保存
4. 確認済みON → `stores.collocation_checked=1`（併設メンバーまとめて更新）→ ピンに緑✓、凡例に表示

### 追加・変更

| 何 | 場所 |
|----|------|
| DBフラグ・CRUD | `python/desktop/database/store_db.py`（`collocation_checked`） |
| Places 近傍検索 | `python/desktop/services/google_maps_service.py`（`search_nearby_hardoff_collocations`） |
| ポップアップ・✓・ハンドラ | `python/desktop/ui/store_master/route_map_widget.py` |
| テスト | `python/desktop/tests/test_route_map_collocation_register.py` |

### 確認（実機）

1. HIRIO を再起動（設定タブに Google Maps APIキーがあること）
2. データベース管理 → 店舗マスタ → ルート地図
3. H1 ピンを開き、自動検索または「併設を自動確認」で候補が出るか
4. 候補「登録」で DB 追加 → ピンが H2/H3 になるか
5. 「併設確認済み」にチェック → ピンに ✓ が付くか

### 次の一手

1. 上記の実機確認

---

## 2026-10-04 ルート地図・周回編集と WEBテンプレート作成

訪問スキップ・地図クリック順・スタート／ゴール・WEBテンプレ作成までをルート地図から一連でできるようにした。

### 動き

1. 店舗リストのチェックOFF＝行かない。地図はグレーicon、最後の訪問店から薄い点線。保存は `template_include`
2. 店舗をクリックすると地図iconが拡大。編集中ルートにスタート／ゴールラベル
3. 「訪問順序反転」で周回順を逆にし保存
4. 「地図上で訪問順序選択」ON → 店を順にクリック（再クリックで解除）。戻る／進む／訪問順序保存。ルート選択解除で全体マップ
5. 「WEBテンプレート作成」→ 最大化可能な左右分割ダイアログ。開いた時点で Google マップ表示（ルート選択の再読込相当）。画面内で訪問順反転可。作成で route.json 等を生成

### 追加・変更

| 何 | 場所 |
|----|------|
| ルート地図UI一式 | `python/desktop/ui/store_master/route_map_widget.py` |
| WEBテンプレダイアログ | `python/desktop/ui/store_master/web_template_dialog.py`（新規） |
| WEBテンプレ作成共通処理 | `python/desktop/services/route_web_template_create.py`（新規） |
| display_order＋template_include 並べ替え | `python/desktop/services/store_route_membership_service.py` |

### 確認

1. HIRIO を再起動
2. ルート地図 → ルート名ダブルクリック
3. チェックOFF → グレー＋点線。選択 → icon拡大。スタート／ゴール表示
4. 地図上で訪問順序選択 → クリックで線が伸びる／戻る・進む
5. WEBテンプレート作成 → 地図確認 → 必要なら反転 → 作成

### 次の一手

- 実機で WEBテンプレ作成後のスマホURL・ルート保険コピーを確認
- Embed が出ない場合は設定の Google Maps APIキーと Maps Embed API 有効化を確認


## 2026-10-04 ルート地図・左パネルと訪問順編集

ルート地図を現場で触りやすいUIにし、周回順を地図から直せるようにした。

### 動き

1. 左パネルはルート／店舗／タグの3段。見出しクリックで畳む／開く。畳むと他段が高さを受け取る
2. 左と地図のあいだ、左3段のあいだの区切り線をドラッグ → 幅・高さを変更。次回起動でも同じ
3. チェック枠: 地図への表示オン／オフ。ルート名ダブルクリック: 店舗一覧表示＋地図拡大
4. 店舗をドラッグ並べ替え → 「訪問順序保存」→ マスタ表示順＋最新ルート登録の訪問順を更新

### 追加・変更

| 何 | 場所 |
|----|------|
| 折りたたみセクション | `python/desktop/ui/store_master/collapsible_section.py`（新規） |
| 地図左パネル・訪問順・サイズ保存 | `python/desktop/ui/store_master/route_map_widget.py` |
| 地図からのルート変更を一覧・カンバン同期 | `python/desktop/ui/store_master/widget.py` |
| 最新サマリー取得・訪問順更新 | `python/desktop/database/route_db.py` |

### 確認

1. HIRIO を再起動
2. データベース管理 → 店舗マスタ → ルート地図
3. 左がダーク／白文字か、畳むと他段が広がるか、区切り線のサイズが再起動後も残るか
4. ルート名ダブルクリック → 店舗並べ替え → 訪問順序保存 → 地図の線順と店舗一覧の並び


## 2026-10-04 店舗マスタ・テキスト貼り付け取込

店舗名リストをメモ帳などから貼り付けて、CSVインポートと同じ流れで取り込む。

### 動き

1. 店舗一覧「テキスト貼り付け」→ ダイアログに店名を1行ずつ貼る → 取り込み開始
2. 空行と `#` 行は無視。CSV／テキスト共通で `import_takeout_places`
3. DBに無い店だけ追加。原則未所属。HA/HO/OF が 80m 以内なら既存と同ルート
4. **修正:** ハードオフ系の別ブランド併設は、住所・電話・座標が同じでも重複スキップしない

### 追加・変更

| 何 | 場所 |
|----|------|
| ボタン・ダイアログ | `python/desktop/ui/store_master/store_list.py` |
| テキスト解析・共通取込・併設重複例外 | `python/desktop/services/google_takeout_favorites_import.py` |
| テスト | `python/desktop/tests/test_google_takeout_favorites_import.py` |

### 確認（実機）

1. HIRIO を再起動
2. テキスト貼り付けで `ホビーオフ 埼玉東松山店` / `ホビーオフ 高麗川店` などを取り込む
3. ハードオフと並んでホビーオフが店舗一覧に出るか

### 次の一手

1. 上記の実機確認（併設ホビーオフ追加）

---
## 2026-10-03 巡回Web・店舗備考連携＋自動保存

現場の撮影・巡回画面（`/route/{web_id}`）で、店舗マスタの備考を見ながら追記し、保存忘れを減らす。

### 動き

1. Webテンプレ作成（ルート選択）時、訪問表／店舗マスタの備考が `route.json` の各店 `notes` に入る（既存）
2. 巡回画面の各店カードで、仕入点数の下に備考テキストエリアを表示
3. `GET /api/route/{web_id}` で備考が空なら店舗マスタから補完（古い route.json 向け）
4. `PUT /api/route/{web_id}` で備考が変わった店だけ `StoreDatabase.set_store_notes_by_code` でマスタ上書き
5. 入力／「今の時刻」後に debounce 自動保存（`keepForm` で DOM 再構築しない）。手動「保存」も可

### 追加・変更

| 何 | 場所 |
|----|------|
| 画面・自動保存 | `python/route_web/static/route.html` |
| GET補完・PUT同期 | `python/route_web/app.py` |
| マスタ同期ヘルパー | `python/route_web/store_notes_sync.py`（新規） |
| 仕様 | `docs/specs/field_route_web_spec.md` |

### 確認（実機）

1. ルートWebを再起動（番人 `watch.ps1` / タスク `HIRIO_route_web`、または `start_route_web.bat`）
2. ルート選択で Webテンプレート作成 → スマホで開く
3. 各店に店舗マスタと同じ備考が出るか
4. 備考を追記 → しばらく待つ／または保存 → データベース管理→店舗マスタ→店舗一覧の備考が更新されるか
5. IN時刻を入れて画面を閉じずに再読込 → 消えていないか（自動保存）

### 次の一手

1. ルートWeb再起動後、実機（スマホ）で備考表示・追記・自動保存を確認
2. 店舗一覧を開き直してマスタ備考の反映を確認

---
## 2026-10-03 ネット仕入箱・SKU全文編集

店舗ルート（仕入帳）とは別系統。親フォルダ例: `D:\せどり総合\ネット仕入れリスト`（設定キー `online_purchase/root_dir`、無ければ既定候補）。

### 動き

1. ネット仕入タブで日付箱を1クリック作成 → `YYYY-MM-DD-フリマ` 等＋ `仕入CSV`／`商品画像`／`証憑スクショ`
2. `route.json` に `box_kind=online`・`route_code=NET`。`ensure_online_route_registration` で route_web 登録
3. **DB保存** 後に `write_photo_candidates` → 箱内 `photo_candidates.json`。専用の「スマホ用ボタン」はサイト側に置かない
4. スマホは https でトップ → ネット箱 → `/route/{web_id}/photos`（既存商品撮影UI）
5. CSV取込: `find_stocklist_csv` が `StockList_*.csv` のあと任意 `*.csv` も探す
6. 仕入行の編集: SKU全文編集 → purchases／products／ledger の rename。一覧は SKU変更時フル再描画

### 追加・変更

| 何 | 場所 |
|----|------|
| 箱作成・候補書込 | `python/desktop/services/online_box.py` |
| サーバ側 online 同期 | `python/route_web/online_sync.py` |
| DB保存後の準備 | `python/desktop/ui/inventory/workflow_mixin.py` |
| 設定 | `python/desktop/utils/settings_helper.py`（`online_purchase/*`） |
| CSV任意名 | `python/desktop/services/route_folder_import.py` |
| SKU全文＋台帳同期 | `purchase_row_edit/dialog.py` / `fee_channel_mixin.py` |
| 一覧即反映 | `python/desktop/ui/product/purchase_edit_mixin.py` |
| route_web UI/API | `app.py` / `registry.py` / `route_purchases.py` / `schema.py` / `server_helper.py` / `static/index.html` / `route_photos.html` |
| テスト | `python/desktop/tests/test_online_box.py`（＋ `test_route_web_phase235.py` 追記） |

### 確認コマンド

```text
cd C:\HIRIO\repo\sedori-app.github
.venv\Scripts\python.exe -m pytest python/desktop/tests/test_online_box.py -q
```

### 次の一手（実機）

1. HIRIO とルートWebを一度再起動
2. ネット仕入で箱作成 → CSV投入 → DB保存 → https で候補が出るか
3. 仕入行の編集で SKU を直し「反映」→ 一覧と古物台帳がすぐ変わるか

---

## 2026-09-27 商品撮影（ルート単位）

仕入を保存したあとの `/route/{web_id}/photos` で撮る。店舗は選ばない。画面にはルート名と日付を出す。

### 動き

1. 候補は、そのルートの仕入DB。同じJANが無ければDB全体。それでも無ければ、日付が近いルート（21日以内を優先。無ければ近い順に3ルート）
2. 写真は `{ルート箱}/商品画像/`。ファイル名は `{route_date}-{route_code}-item-{連番}.jpg`
3. JAN付きの写真は、撮影終了を待たずに画像DBへ書く。ASINだけの写真は画像DBのJAN欄には入らない
4. 撮影終了を押すと、その商品は「撮影済み」へ移る。タップすると再撮影を聞き、はいなら写真を消して一覧に戻す
5. 新品など写真が不要な商品は、リストを長押しして「画像不要」。撮影済みへバッジ付きで移る。リストが空ならそのルートの撮影は終わり。撮影済みからタップすると一覧に戻せる
6. スマホは Tailscale をオンにして `https://houseserver.tail0a340c.ts.net/` を開くと、カメラを開いたまま続けて撮れる。縦持ちのまま、保存は中央の横長（4:3）。`http://houseserver:8792` は1枚ずつ

### 追加・変更

| 何 | 場所 |
|----|------|
| 画面 | `python/route_web/static/route_photos.html` / `route_photos_done.html` |
| API | `python/route_web/app.py`（`POST /api/route/{web_id}/products`、確定、画像不要、撮影済み） |
| 保存と確定 | `python/route_web/product_images.py` |
| 候補の探し方 | `python/route_web/route_purchases.py` |
| 画像DBへの先書き | `python/desktop/services/route_product_seed.py` |
| https | `python/route_web/enable_https.ps1`（Tailscale Serve。実行は Tailscale を掴んでいるユーザー） |
| 仕様 | `docs/specs/field_route_web_spec.md` |

反映にはルートWebの再起動。仕様書の Notion ページは更新しない（2026-09-26 の方針）。

---

## 2026-09-23 情報撮影（メルカリ証憑）

ネット仕入で、出品URL（`https://jp.mercari.com/item/m...`）がある行を、ログイン済みの普段のChromeで3枚撮る。新しい空のChromeは使わない（ログインが切れるため）。パスワードは保存しない。

### 動き

1. 行を選んで「情報撮影」（未選択なら、メルカリURLがある行全部）
2. HIRIO が `127.0.0.1:8765` で待ち、いまの Chrome にそのページを開く
3. 拡張が商品の上、説明までスクロール、取引画面の3枚を撮る
4. 証憑フォルダへ保存し、取引IDが空なら入れ、ユーザー名が空か配送表示なら入れ直す
5. ログインを求められたら「続ける／中止」。人がログインしてから続ける

### 追加・変更

| 何 | 場所 |
|----|------|
| ボタン | `python/desktop/ui/inventory/widget.py`（ネット仕入のときだけ） |
| 待ち受けと保存 | `python/desktop/ui/inventory/mercari_capture_mixin.py` |
| 拡張 | `python/desktop/mercari_capture_extension`（manifest 1.0.2） |
| URLの正規化 | `python/desktop/services/mercari_evidence_capture.py` |
| 出品者名 | `python/desktop/services/flea_market_evidence_ocr.py`（配送表示を飛ばす） |
| サムネ拡大 | `python/desktop/ui/inventory/flea_evidence_panel.py` |
| 手入力を残す | `python/desktop/ui/inventory/row_edit_dialog.py`（OK時は OCR 通知を切る。空欄だけ埋める。「取引画面をOCRして入力」は上書き） |

### 使う前

1. HIRIO を終了して起動し直す
2. `chrome://extensions` で「HIRIO メルカリ撮影」を読み込む（更新したあとは再読み込み。サイトへのアクセスを許可）
3. 出品URLが空の行は撮らない

### 試験

- ログイン済みChromeで3枚保存できた（商品・説明・取引画面）
- 出品者「よう」の前に「ゆうパケットプラスでお届け」があっても、読み取りは「よう」
- 行の編集でユーザー名を直してOKすると、その名前が残る（2026-09-25: OK時の再OCRが上書きしていたのを止めた。再起動後に画面で確認）
- 「サイズ:厚さ7cm以内重さ2kg以内」は出品者名にしない（テストで「よう」になることを確認）

---

## 2026-09-23 ルート一覧の番人とアイコン

### 追加・変更

| 何 | 場所 |
|----|------|
| 番人 | `python/route_web/watch.ps1`（15秒ごとに 8792 を見る） |
| タスク | `HIRIO_route_web`（ログオン・起動2分後・5分おき）。登録は `watch.ps1 -Install` |
| 再起動後 | watcher の `hirio_boot_recover.ps1` がこの番人も起こす |
| 待ち受け | `app.py` の `main()` が IPv4 と IPv6 の両方で 8792 を待つ（`houseserver` は IPv6 が先） |
| アイコン | `python/route_web/static/icon.png`（表示名「ルート巡回」） |
| ログ | `python/route_web/logs/`（gitignore） |

### 試験

- プロセスを止めると、約9秒後に `http://127.0.0.1:8792/health` が戻った
- `http://houseserver:8792/health` は IPv4 と IPv6 の両方で 200
- `/icon.png` `/apple-touch-icon.png` `/manifest.webmanifest` が 200
- スマホのホームに既にある場合は、一度外して追加し直すとアイコンが変わる

---

## パス（このマシン）

| 何 | 場所 |
|----|------|
| リポジトリ | `C:\HIRIO\repo\sedori-app.github` |
| 起動 | `start_hirio.bat` または `.venv\Scripts\python.exe python\desktop\main.py` |
| 本番DB | `python\desktop\data`（`hirio.db` / `hirio_product_purchase.db` / `hirio_inventory_route.db` など） |
| 設定 | `config` |
| 画像・CSV | `D:\せどり総合`（USB SSD。パス置換しない） |
| NASバックアップ | `Z:`（HIRIOから直接開かない） |
| 直下の `data` | 本番DBではない |

---

## 2026-09-21 夜にやったこと（証憑・全件OCR）

### 症状

証憑管理 → レシート・領収書・保証書 でフォルダ選択して全件OCRすると、**中身を読まずに完了**していた。

### 原因（ミニPC移植）

1. **Tesseract OCR 本体が未導入**（`pytesseract` だけ入っていて `tesseract.exe` が無い）
2. 入れた直後は **日本語データ `jpn.traineddata` も無かった**（英語だけ）
3. 全件OCRは失敗してもダイアログを出さず次へ進み、最後に「完了」と出していた
4. Windows 版 Tesseract は `TESSDATA_PREFIX` を tessdata **フォルダ自体**にする（親フォルダだと言語を読めない）

### このPCに入れたもの

| 何 | 場所 |
|----|------|
| Tesseract 5.4.0 | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| 日本語（tessdata_fast） | 同じ `tessdata\jpn.traineddata` |
| 予備コピー | `C:\HIRIO\tools\tessdata` |
| pillow-heif | venv（iPhone の HEIC 用） |

### コードの直し

| ファイル | 役割 |
|----------|------|
| `python/desktop/utils/ocr_runtime.py` | exe / tessdata 自動検出、画像収集、日本語データ補完 |
| `python/desktop/services/ocr_service.py` | 開始前点検、無効な前PCパスを捨てる |
| `python/desktop/ui/receipt/ocr_mixin.py` | 失敗を隠さない。進捗ラベル。HEIC対応 |
| `python/desktop/ui/receipt/support.py` | QThread の `finished` 衝突を回避（`result_ready`） |
| `python/desktop/utils/image_processor.py` | 長辺1920へ縮小（ミニPCのメモリ対策） |
| `python/desktop/services/receipt_service.py` | 保存先を `python/desktop/data/receipts` に修正 |

### 試験

```
ok collect_top / collect_recursive / prefix / limit
ok smoke_ocr_digits  → TOTAL 1234 を Tesseract が読めた
ok receipt parse tests
```

**2026-09-22 実機:** フォルダ選択→全件OCR OK。レシート一覧に反映。一部は日付・合計が空（OCR精度）。

### 次（実機）

1. **一括マッチング** → 手動調整 → 一括リネーム → GCS → 確定
2. 精度を上げたい行は設定の **Gemini APIキー** を入れる（レシート解析は Gemini 優先）

---

## 2026-09-21 夜にやったこと（画像管理・FastAPI）

### 症状と直し

1. **スキャンが仕入JANに紐付かない**  
   ミニPCに Java / pyzbar が無く、バーコードが読めなかった。  
   → `zxing-cpp`（Java不要）を優先。`requirements.txt` に追加。

2. **スキャン中に RecursionError**  
   Qt の `eventFilter` が再入していた。  
   → `python/desktop/utils/event_filter_safety.py` でガード。

3. **Ctrl 複数選択が重い**  
   選択のたびに一覧を作り直していた。  
   → 選択ロジックを軽くした（`compute_image_multi_select`）。

4. **仕入DB候補が今のJANしか出ない**  
   → 撮影日時±7日の他JANも出し、今のJANを先頭にする。

5. **選んだ写真だけでなく JANグループ全部が別商品に付く**  
   → 中央リストの選択画像だけ `update_image_paths_for_jan` / `assign_image_to_jan`。  
   元の仕入レコードからはそのパスを外す。  
   左ツリーのJANグループ右クリックは、今までどおりグループ全体。

6. **FastAPI**  
   起動時に静かに自動起動。閉じるときは確認ダイアログを出さない。

### 主なファイル

| ファイル | 役割 |
|----------|------|
| `python/desktop/services/image_service.py` | zxing-cpp でJAN読取 |
| `python/desktop/ui/image_manager/scan_mixin.py` | スキャン時の安全化 |
| `python/desktop/ui/image_manager/purchase_link_mixin.py` | 選択画像だけ紐付け |
| `python/desktop/ui/image_manager/support.py` | `resolve_link_image_paths` |
| `python/desktop/ui/product/purchase_edit_mixin.py` | 候補マージ＋旧レコードからパス解除 |
| `python/desktop/ui/main_window.py` | FastAPI 自動起動 |
| `python/desktop/utils/event_filter_safety.py` | eventFilter 再入防止 |
| `requirements.txt` | `zxing-cpp` |

### 試験

venv に pytest は無いので関数を直接実行。

```
ok test_resolve_link_image_paths_uses_selected_subset
ok test_resolve_link_image_paths_falls_back_to_group_when_empty
ok test_remove_image_paths_leaves_other_sku_images
ok test_merge_keeps_other_jans_and_puts_current_first
```

複数選択・eventFilter・zxing-cpp 名のテストも同系統。

実機（選んだ写真だけ別商品へ移る）は **HIRIO 再起動後**に確認。古いプロセスのままでは直っていない。

### 次（実機）

1. 今動いている HIRIO を閉じて `start_hirio.bat` で開き直す
2. 画像管理で JANグループを開き、中央で数枚だけ選ぶ（緑枠）
3. **仕入DB候補紐付け** → 別商品を選ぶ
4. 選んだ枚数だけ新しいJANグループ／仕入レコードへ移り、残りは元のグループに残ること
5. 左のJANグループを右クリックしたときは、グループ全体の紐付けのままであること

---

## 2026-09-21 午後にやったこと（環境）

1. `feature/sp-api` を `git pull`（進捗ログ取り込み含む）
2. Python 3.13 が無かったので winget で 3.13.15 を導入
3. 壊れた `.venv`（メインPCの Python313 を指していた）を `.venv_old` にリネーム
4. `py -3.13 -m venv .venv` → pip → 依存関係導入
   - `PySide6-WebEngine` という独立パッケージは無い → `PySide6`（Addons に WebEngine 含む）を入れた
   - `google-generativeai` は他 Google 系と同時解決すると止まるので、あとから単独インストール
5. HIRIO 画面起動。仕入DB表示OK。`start_hirio.bat` 作成（デスクトップショートカットからも起動可）

---

## 2026-09-22 現場ルートWeb Phase 1

### 追加したもの

| 何 | 場所 |
|----|------|
| 仕様書 | `docs/specs/field_route_web_spec.md` |
| 時刻Web | `python/route_web/`（`:8792`） |
| **固定URL** | `http://houseserver:8792/`（一覧。スマホはこれだけブックマーク） |
| 起動 | 番人 `python/route_web/watch.ps1`（タスク `HIRIO_route_web`）。手動は `start_route_web.bat`。Webテンプレ作成時も自動起動 |
| ボタン | ルート選択「テンプレート生成」の右隣「Webテンプレート作成」 |

### 試験

```
ok route_web schema/registry
ok phase1-api-verify（GET/PUT departure_time・HTMLに今の時刻）
```

### ユーザー確認（残り）

1. スマホで **一度だけ** `http://houseserver:8792/` をブックマーク（Tailscale ON）
2. HIRIO 再起動 → ルート選択で「Webテンプレート作成」
3. 固定URLを開き、日付＋ルート名をタップ →「今の時刻」→ 保存
4. 既存「テンプレート生成」で xlsx が今までどおりできること

---

## 次

1. HIRIO とルートWebを再起動し、巡回画面に商品撮影が無いこと、事前処理、撮影画面を実機で見る
2. 次の仕入で、CSV送信 → 事前処理 → 帰宅後の箱取込 → 照合 → プライスター → 商品撮影
3. 不具合は都度 `feature/sp-api` で修正
4. 証憑管理いじり時: `purchase_item_count` vs アマサーチ件数の差異チェック
5. 1.5b 撮影直後OCRは当面やらない
6. rclone は停止済み。ドライブが同期するのは `ルート保険` だけ。HIRIO 再起動後に Webテンプレ作成で箱ができること、出かける前に同期完了を見ること

---

## 2026-09-22 rclone 安定化（ホワイトアウト対策）

### 症状と対処

| 症状 | 原因 | 対処 |
|------|------|------|
| Drive スキップ | GUI の PATH に rclone 無し | `find_rclone_exe` が WinGet Links／Packages も探す。`rclone_exe` フルパス可 |
| Webテンプレ後に白画面 | UI スレッドで `rclone mkdir`（60s×2）が固まる | **バックグラウンド QThread**＋**mkdir 省略・copy のみ** |
| 地図が真っ黒／切断 | WebEngine 内 Google Maps | 失敗時プレースホルダ＋「ブラウザで開く」案内 |

### 触ったファイル

- `python/desktop/services/rclone_route_drive.py`
- `python/desktop/ui/route_summary/template_mixin.py`（`_RclonePushWorker`）
- `python/desktop/ui/route_summary/map_mixin.py`
- `config/rclone_route_drive.example.json`
- `python/desktop/tests/test_rclone_route_drive.py`

### 運用の理解

- **ローカル仕入帳を Google Drive アプリで常時同期する必要はない**
- HIRIO がテンプレ作成時に **必要な箱だけ rclone で送る**（一方向・そのタイミング）

---

## 2026-09-22 現場ルートWeb Phase 2 / 3 / 5

### 追加

| 何 | 場所 |
|----|------|
| CSV受信箱 | `python/route_web/csv_inbox.py` … `D:\…\仕入CSV_受信` |
| 商品画像 | `python/route_web/product_images.py` |
| API | `python/route_web/app.py` v0.2.0 |
| UI | `python/route_web/static/route.html`（仕入CSV＋商品撮影） |
| ルート箱取込 | `python/desktop/services/route_folder_import.py` + 仕入「ルート箱から取込」 |
| 試験 | `python/desktop/tests/test_route_web_phase235.py` |

### 運用メモ

1. Webテンプレ作成 → ローカル箱＋Excel。**rclone 有効なら裏で Drive にも同じ箱**（完了時ダイアログ）
2. CSV はスマホから Drive の `仕入CSV\` へ直送
3. ミニPC生存時: ルートWebで IN/OUT・レシート・商品撮影
4. ミニPCダウン時: Drive 上の Excel で滞在時刻
5. 帰宅後: 仕入タブ「ルート箱から取込」

rclone 初回: `python\route_web\check_rclone.bat` → example を `config\rclone_route_drive.json` にコピーして enabled（フルパス推奨）

### やらない（確定）

- 1.5b 撮影直後OCR
- スマホのバーコード自動読取（Phase 5 第1弾）
- Tailscale 共有で受信箱パスを固定する運用（技術的に不可）
- rclone mount（配布は **copy のみ**。mkdir は使わない）
- 仕入帳全体のドライブ同期はしない（約23GB）。同期するのは `ルート保険` だけ

---

## やらないこと

- メインPCとミニPCで同じ本番DBを同時に開く
- メインPCの `.venv` を再度コピーする
- `python\desktop\data` を空のDBで上書きする
- SQLite を `Z:` に置く
- `HIRIOold/`・`.bak_phase*`・DBバックアップ・レシートスナップショットを Git に載せない

---

## 一時停止メモ（事務PWA）

- 枝 `feature/server-pwa` / 到達点 `12e3240`（仕入 ルートテンプレ＋DB保存まで）
- 再開時の次手: ⑦古物台帳生成
- 2026-09-21 以降、PWA は後回し。先にミニPC上のデスクトップで開発・運用する
