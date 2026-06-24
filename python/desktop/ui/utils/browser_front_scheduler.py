#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ブラウザ起動直後に複数回フォアグラウンド化を試みる。"""

from __future__ import annotations

from functools import partial
from typing import Iterable, Optional, Sequence

from PySide6.QtCore import QTimer

try:
    from utils.win_browser_helper import bring_browser_to_front, set_browser_topmost
except ImportError:
    from desktop.utils.win_browser_helper import (  # type: ignore
        bring_browser_to_front,
        set_browser_topmost,
    )

_DEFAULT_DELAYS_MS: Sequence[int] = (200, 600, 1200, 2000, 3500, 5000)


def schedule_bring_browser_to_front(
    title_keywords: Iterable[str],
    *,
    delays_ms: Sequence[int] = _DEFAULT_DELAYS_MS,
    pin_topmost_until_ms: Optional[int] = None,
) -> None:
    """
    ブラウザの読み込み待ちを考慮し、遅延しながら前面化を繰り返す。

    pin_topmost_until_ms: 指定時はその時間まで TOPMOST 固定（ページ表示待ち用）
    """
    keywords = list(title_keywords)
    if not keywords:
        return

    for delay in delays_ms:
        QTimer.singleShot(int(delay), partial(bring_browser_to_front, keywords))

    if pin_topmost_until_ms is not None and pin_topmost_until_ms > 0:
        QTimer.singleShot(150, partial(set_browser_topmost, keywords, True))
        QTimer.singleShot(
            int(pin_topmost_until_ms),
            partial(set_browser_topmost, keywords, False),
        )
