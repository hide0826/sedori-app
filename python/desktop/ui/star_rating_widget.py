#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星評価ウィジェット

クリック可能な5段階星評価ウィジェット
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QMouseEvent


class StarRatingWidget(QWidget):
    """星評価ウィジェット（5段階評価）"""
    
    rating_changed = Signal(int)  # 評価が変更されたときに発火
    
    def __init__(self, parent=None, rating: int = 0, star_size: int = 14):
        super().__init__(parent)
        self._rating = max(0, min(5, rating))  # 0-5の範囲に制限
        self.setMaximumHeight(22)
        
        # 星のサイズと間隔
        self.star_size = max(10, min(20, star_size))
        self.star_spacing = 3
        
    def setRating(self, rating: int):
        """評価を設定"""
        old_rating = self._rating
        self._rating = max(0, min(5, rating))
        if old_rating != self._rating:
            self.update()
            self.rating_changed.emit(self._rating)
    
    def rating(self) -> int:
        """現在の評価を取得"""
        return self._rating
    
    def paintEvent(self, event):
        """描画イベント"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 星の色（塗りつぶし: 黄色、枠: 灰色）
        filled_color = QColor(255, 215, 0)  # ゴールド
        empty_color = QColor(200, 200, 200)  # グレー
        
        # 星の文字
        star_char = "★"
        font = QFont("Segoe UI Symbol", self.star_size)
        painter.setFont(font)
        
        # フォントメトリクスを取得してテキストの高さを取得
        metrics = painter.fontMetrics()
        text_height = metrics.height()
        
        # 5つの星を描画
        for i in range(5):
            x = i * (self.star_size + self.star_spacing)
            y = (self.height() - text_height) // 2 + metrics.ascent()
            
            # 評価に応じて色を決定
            if i < self._rating:
                painter.setPen(filled_color)
            else:
                painter.setPen(empty_color)
            
            # 星を描画
            painter.drawText(x, y, star_char)
    
    def mousePressEvent(self, event: QMouseEvent):
        """マウスクリックイベント"""
        if event.button() == Qt.LeftButton:
            # クリック位置から星の番号を計算
            x = event.pos().x()
            star_index = x // (self.star_size + self.star_spacing)
            
            # クリック位置が星の右半分なら+1
            offset_in_star = x % (self.star_size + self.star_spacing)
            if offset_in_star > self.star_size / 2:
                star_index += 1
            
            # 評価を設定（1-5、0は評価なし）
            new_rating = max(1, min(5, star_index + 1))
            
            # 同じ星をクリックした場合は0にリセット
            if new_rating == self._rating:
                new_rating = 0
            
            self.setRating(new_rating)
    
    def sizeHint(self):
        """推奨サイズ"""
        from PySide6.QtCore import QSize
        width = 5 * (self.star_size + self.star_spacing) - self.star_spacing
        return QSize(width, self.star_size + 10)

