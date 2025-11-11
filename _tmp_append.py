from pathlib import Path
path = Path('docs/handover_prompt_route_summary_complete.md')
text = path.read_text(encoding='utf-8')
addition = '\n\n### 2025-11-11\n- 仕入管理タブにルートテンプレート読み込み／表示モード切替／統合スナップショット保存を実装。ルート登録タブは登録とテンプレート生成に専念できる構成に整理。\n- 仕入データとルート情報を一括で保存・復元できる inventory_route_snapshots を追加。仕入管理タブ単体で再編集できる運用に移行。\n'
if addition.strip() not in text:
    path.write_text(text + addition, encoding='utf-8')
