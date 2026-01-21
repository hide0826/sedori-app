from PySide6.QtWidgets import QTableView, QHeaderView
from PySide6.QtCore import QSettings

def save_table_header_state(table_view: QTableView, settings_key: str):
    """
    QTableViewのヘッダーの状態をQSettingsに保存します。

    Args:
        table_view (QTableView): 対象のテーブルビュー。
        settings_key (str): 保存に使用する設定キー。
    """
    if not table_view:
        return
    settings = QSettings("HIRIO", "SedoriApp")
    settings.setValue(settings_key, table_view.horizontalHeader().saveState())

def restore_table_header_state(table_view: QTableView, settings_key: str):
    """
    QSettingsからQTableViewのヘッダーの状態を復元します。

    Args:
        table_view (QTableView): 対象のテーブルビュー。
        settings_key (str): 復元に使用する設定キー。
    """
    if not table_view:
        return
    settings = QSettings("HIRIO", "SedoriApp")
    header_state = settings.value(settings_key)
    if header_state:
        table_view.horizontalHeader().restoreState(header_state)

def save_table_column_widths(table_view: QTableView, settings_key: str):
    """
    テーブルの列幅のみをQSettingsに保存します（リサイズモードは保存しない）。

    Args:
        table_view (QTableView): 対象のテーブルビュー。
        settings_key (str): 保存に使用する設定キー。
    """
    if not table_view:
        return
    header = table_view.horizontalHeader()
    column_count = header.count()
    if column_count == 0:
        return
    
    settings = QSettings("HIRIO", "SedoriApp")
    widths = []
    for col_idx in range(column_count):
        widths.append(header.sectionSize(col_idx))
    settings.setValue(settings_key, widths)

def restore_table_column_widths(table_view: QTableView, settings_key: str):
    """
    QSettingsからテーブルの列幅のみを復元します（リサイズモードは変更しない）。

    Args:
        table_view (QTableView): 対象のテーブルビュー。
        settings_key (str): 復元に使用する設定キー。
    """
    if not table_view:
        return
    header = table_view.horizontalHeader()
    column_count = header.count()
    if column_count == 0:
        return
    
    settings = QSettings("HIRIO", "SedoriApp")
    widths = settings.value(settings_key)
    if widths and isinstance(widths, list):
        for col_idx, width in enumerate(widths):
            if col_idx < column_count:
                try:
                    w = int(width)
                    # 幅0（列を非表示にしていたときに保存されがち）を復元すると、
                    # 列が表示されていても「見えない」状態になるためスキップする。
                    # ※ユーザーが意図的に0幅にする運用は現実的にないので問題になりにくい。
                    if w <= 0:
                        continue
                    header.resizeSection(col_idx, w)
                except (ValueError, TypeError):
                    pass



