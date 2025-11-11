#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星評価ウィジェット

クリック可能な5段階星評価ウィジェット
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QMouseEvent, QRegion


class StarRatingWidget(QWidget):
    """星評価ウィジェット（5段階評価）"""
    
    rating_changed = Signal(float)  # 評価が変更されたときに発火
    
    def __init__(self, parent=None, rating: float = 0.0, star_size: int = 14):
        super().__init__(parent)
        self._rating = max(0.0, min(5.0, float(rating)))  # 0-5の範囲に制限
        self.setMaximumHeight(22)
        
        # 星のサイズと間隔
        self.star_size = max(10, min(20, star_size))
        self.star_spacing = 3
        
    def setRating(self, rating: float):
        """評価を設定"""
        rating = round(float(rating) * 2) / 2  # 0.5刻み
        rating = max(0.0, min(5.0, rating))
        if abs(self._rating - rating) > 1e-4:
            self._rating = rating
            self.update()
            self.rating_changed.emit(self._rating)
    
    def rating(self) -> float:
        """現在の評価を取得"""
        return self._rating
    
    def paintEvent(self, event):
        """描画イベント"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._value_text_width = 0
        
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
            
            # 常に空星を描画
            painter.setPen(empty_color)
            painter.drawText(x, y, star_char)

            fraction = self._rating - i
            if fraction <= 0:
                continue

            fraction = min(1.0, fraction)
            painter.save()
            clip_rect = QRegion(x, 0, int(self.star_size * fraction), self.height())
            painter.setClipRegion(clip_rect)
            painter.setPen(filled_color)
            painter.drawText(x, y, star_char)
            painter.restore()

        # 数値表示
        value_text = f"{self._rating:.1f}"
        painter.setClipRect(event.rect())
        painter.setPen(QColor(220, 220, 220))
        value_font = QFont("Segoe UI", max(8, self.star_size - 6))
        painter.setFont(value_font)
        text_x = 5 * (self.star_size + self.star_spacing)
        text_y = (self.height() + painter.fontMetrics().ascent()) // 2 - 2
        painter.drawText(text_x + 4, text_y, value_text)
        self._value_text_width = painter.fontMetrics().horizontalAdvance(value_text)
    
    def mousePressEvent(self, event: QMouseEvent):
        """マウスクリックイベント"""
        if event.button() == Qt.LeftButton:
            # クリック位置から星の番号を計算
            x = event.pos().x()
            star_index = x // (self.star_size + self.star_spacing)
            
            # クリック位置が星の右半分なら+1
            offset_in_star = x % (self.star_size + self.star_spacing)
            fraction = 0.5 if offset_in_star < self.star_size / 2 else 1.0
            new_rating = max(0.5, min(5.0, star_index + 1 if fraction == 1.0 else star_index + 0.5))
            
            if abs(new_rating - self._rating) < 1e-4:
                new_rating = 0.0
            
            self.setRating(new_rating)
    
    def sizeHint(self):
        """推奨サイズ"""
        from PySide6.QtCore import QSize
        width = 5 * (self.star_size + self.star_spacing) - self.star_spacing + 36
        return QSize(width, self.star_size + 10)

