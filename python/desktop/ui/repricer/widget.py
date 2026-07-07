"""価格改定ウィジェット（オーケストレーター）。"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Signal, QSettings
from typing import Dict, Optional

from utils.error_handler import ErrorHandler

from .workflow_mixin import RepricerWorkflowMixin
from .file_panel_mixin import RepricerFilePanelMixin
from .preview_mixin import RepricerPreviewMixin
from .result_mixin import RepricerResultMixin


class RepricerWidget(
    RepricerWorkflowMixin,
    RepricerFilePanelMixin,
    RepricerPreviewMixin,
    RepricerResultMixin,
    QWidget,
):
    """価格改定ウィジェット"""

    repricing_executed = Signal(str)

    def __init__(self, api_client, mode="standard"):
        super().__init__()
        self.api_client = api_client
        self.mode = mode if mode in ("standard", "369") else "standard"
        self.product_widget = None
        self.csv_path = None
        self.repricing_result = None
        self.error_handler = ErrorHandler(self)
        self.settings = QSettings("HIRIO", "DesktopApp")
        # プレビュー／結果エリア状態
        self.preview_collapsed = False
        self.result_collapsed = False
        # CSVプレビュー用の元データとSKU日数
        self.preview_df = None
        self.preview_days = None
        # 日数フィルタの現在値（90/180/270/340 または None）
        self.active_days_filter = None
        self.active_result_days_filter = None
        self.keepa_cache = {}
        self._purchase_edit_dialogs = []
        self._last_saved_csv_path: Optional[str] = None
        # SKU → プライスター返却CSVの price に書く手動上書き（自動値上げはしない）
        self._manual_export_prices: Dict[str, int] = {}
        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self._workflow_post_step: Optional[int] = None

        # UIの初期化
        self.setup_ui()

    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部：ファイル操作・アクション（ワークフロー付き）
        self.setup_file_selection()

        # 中央：プレビューと結果表示エリア
        self.setup_content_area()

    def set_product_widget(self, product_widget):
        """商品DBウィジェット参照を受け取り、仕入行編集ダイアログ連携に使う"""
        self.product_widget = product_widget

    def setup_content_area(self):
        """コンテンツエリアの設定"""
        # 3段構成：CSVプレビュー（上段）→ 価格改定結果（下段）

        # 上段：CSVプレビュー（横に大きく）
        self.setup_preview_area_full_width()

        # 下段：価格改定結果
        self.setup_result_area_full_width()
