
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .support import (
    _REPRICER_ACTION_TO_PIPELINE_STEP,
    _format_repricer_status_prefix_html,
    _format_repricer_workflow_pipeline_html,
)


class RepricerWorkflowMixin:
    """価格改定ウィジェットの分割ミックスイン。"""

    def _sync_workflow_status_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑤ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_repricer_status_prefix_html(text, emph)
        pipe = _format_repricer_workflow_pipeline_html(step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)

    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """ワークフロー状態ラベルを更新"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "価格確認" in text:
            self._workflow_active_step = 3
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_status_label()

    def _run_action_with_status(self, action_name: str, action_func):
        """押したボタン名をワークフロー表示に反映してから処理を実行"""
        step = _REPRICER_ACTION_TO_PIPELINE_STEP.get(action_name)
        self._workflow_post_step = None
        try:
            if step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            post_step = getattr(self, "_workflow_post_step", None)
            if post_step is not None:
                self._workflow_active_step = post_step
                self._workflow_post_step = None
            elif step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)
