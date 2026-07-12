"""価格改定ウィジェット: 定数・ワーカー・HTMLヘルパー・共通 import。"""
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import QThread, Signal
from typing import List, Optional

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

try:
    from desktop.services.keepa_service import KeepaService
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore

from utils.error_handler import validate_csv_file, safe_execute
from utils.settings_helper import get_pricetar_repricing_url

_PRICETAR_BROWSER_TITLE_KEYWORDS = ["pricetar", "プライスター"]

# 改定実行タブ用ワークフロー（①〜⑤）
_REPRICER_WORKFLOW_PIPELINE_SEGMENTS = [
    "①ファイル選択",
    "②価格改定プレビュー",
    "③価格確認（目視）",
    "④価格改定実行",
    "⑤結果をCSV保存",
]
_REPRICER_WORKFLOW_PIPELINE_SEP = "\u2010"
_REPRICER_ACTION_TO_PIPELINE_STEP = {
    "ファイル選択": 1,
    "価格改定プレビュー": 2,
    "価格改定実行": 4,
    "結果をCSV保存": 5,
}


def _format_repricer_status_prefix_html(text: str, emphasize: bool) -> str:
    from html import escape
    if not emphasize:
        return f'<span style="color:#cccccc;">{escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{escape(text)}</span>'


def _format_repricer_workflow_pipeline_html(active_step: Optional[int]) -> str:
    from html import escape
    parts: List[str] = []
    for i, seg in enumerate(_REPRICER_WORKFLOW_PIPELINE_SEGMENTS, start=1):
        esc = escape(seg)
        if active_step == i:
            parts.append(f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>')
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _REPRICER_WORKFLOW_PIPELINE_SEP.join(parts)


class NumericTableWidgetItem(QTableWidgetItem):
    """数値ソート用のカスタムTableWidgetItem"""
    
    def __init__(self, value):
        super().__init__()
        self.numeric_value = float(value) if value else 0.0
    
    def __lt__(self, other):
        """小なり演算子をオーバーライドして数値比較を実装"""
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class RepricerWorker(QThread):
    """価格改定処理のワーカースレッド"""
    progress_updated = Signal(int)
    result_ready = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, csv_path, api_client, is_preview=True, mode="standard"):
        super().__init__()
        self.csv_path = csv_path
        self.api_client = api_client
        self.is_preview = is_preview
        self.mode = mode
        
    def run(self):
        """価格改定処理の実行"""
        try:
            # 進捗更新
            self.progress_updated.emit(10)
            
            # API接続確認
            if not self.api_client.test_connection():
                raise Exception("FastAPIサーバーに接続できません。サーバーが起動しているか確認してください。")
            
            self.progress_updated.emit(20)
            
            # 実際のAPI呼び出し
            if self.is_preview:
                result = self.api_client.repricer_preview(self.csv_path, mode=self.mode)
            else:
                result = self.api_client.repricer_apply(self.csv_path, mode=self.mode)
            
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))

