#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ワークフローパネル

1→2→3→4→5の作業フローと進捗バー
一括実行（開始/一時停止/リセット）
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QProgressBar, QGroupBox,
    QFrame, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor, QPalette
import time


class WorkflowStep:
    """ワークフローステップ"""
    
    def __init__(self, step_id, name, description):
        self.step_id = step_id
        self.name = name
        self.description = description
        self.completed = False
        self.in_progress = False


class WorkflowWorker(QThread):
    """ワークフロー実行のワーカースレッド"""
    step_started = Signal(int, str)  # ステップ開始
    step_completed = Signal(int, str)  # ステップ完了
    progress_updated = Signal(int)  # 進捗更新
    workflow_completed = Signal()  # ワークフロー完了
    error_occurred = Signal(str)  # エラー発生
    
    def __init__(self, steps, api_client):
        super().__init__()
        self.steps = steps
        self.api_client = api_client
        self.is_paused = False
        self.should_stop = False
        
    def run(self):
        """ワークフローの実行"""
        try:
            for i, step in enumerate(self.steps):
                if self.should_stop:
                    break
                    
                # ステップ開始
                self.step_started.emit(i, step.name)
                
                # ステップの実行（ダミー処理）
                self.execute_step(step)
                
                if self.should_stop:
                    break
                    
                # ステップ完了
                self.step_completed.emit(i, step.name)
                
                # 一時停止のチェック
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                    
            if not self.should_stop:
                self.workflow_completed.emit()
                
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def execute_step(self, step):
        """ステップの実行"""
        try:
            if step.step_id == 0:
                # 1. 仕入データ取込
                self.execute_inventory_import()
            elif step.step_id == 1:
                # 2. SKU生成
                self.execute_sku_generation()
            elif step.step_id == 2:
                # 3. 出品CSV生成
                self.execute_listing_export()
            elif step.step_id == 3:
                # 4. ピッキングリスト生成
                self.execute_picking_list()
            elif step.step_id == 4:
                # 5. 古物台帳生成
                self.execute_antique_register()
                
        except Exception as e:
            self.error_occurred.emit(f"ステップ {step.step_id + 1} でエラー: {str(e)}")
    
    def execute_inventory_import(self):
        """仕入データ取込の実行"""
        # ダミーデータの作成（実際の実装では、ファイル選択やAPI呼び出し）
        import pandas as pd
        dummy_data = pd.DataFrame({
            'ASIN': ['B0001', 'B0002', 'B0003'],
            '商品名': ['商品1', '商品2', '商品3'],
            '価格': [1000, 2000, 3000]
        })
        
        # 進捗更新
        for i in range(10):
            if self.should_stop:
                break
            while self.is_paused and not self.should_stop:
                time.sleep(0.1)
            time.sleep(0.2)
            self.progress_updated.emit(int((i + 1) / 10 * 100))
    
    def execute_sku_generation(self):
        """SKU生成の実行"""
        try:
            # ダミーデータでSKU生成
            dummy_data = [
                {'ASIN': 'B0001', '商品名': '商品1'},
                {'ASIN': 'B0002', '商品名': '商品2'},
                {'ASIN': 'B0003', '商品名': '商品3'}
            ]
            
            result = self.api_client.inventory_generate_sku(dummy_data)
            
            # 進捗更新
            for i in range(15):
                if self.should_stop:
                    break
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                time.sleep(0.2)
                self.progress_updated.emit(int((i + 1) / 15 * 100))
                
        except Exception as e:
            raise Exception(f"SKU生成エラー: {str(e)}")
    
    def execute_listing_export(self):
        """出品CSV生成の実行"""
        try:
            # ダミーデータで出品CSV生成
            dummy_data = [
                {'sku': '20250101-B0001-0001', '商品名': '商品1', '価格': 1000},
                {'sku': '20250101-B0002-0002', '商品名': '商品2', '価格': 2000}
            ]
            
            result = self.api_client.inventory_export_listing(dummy_data)
            
            # 進捗更新
            for i in range(10):
                if self.should_stop:
                    break
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                time.sleep(0.2)
                self.progress_updated.emit(int((i + 1) / 10 * 100))
                
        except Exception as e:
            raise Exception(f"出品CSV生成エラー: {str(e)}")
    
    def execute_picking_list(self):
        """ピッキングリスト生成の実行"""
        try:
            # ダミーデータでピッキングリスト生成
            dummy_data = [
                {'sku': '20250101-B0001-0001', '商品名': '商品1'},
                {'sku': '20250101-B0002-0002', '商品名': '商品2'}
            ]
            
            result = self.api_client.picking_list_generate(dummy_data)
            
            # 進捗更新
            for i in range(5):
                if self.should_stop:
                    break
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                time.sleep(0.2)
                self.progress_updated.emit(int((i + 1) / 5 * 100))
                
        except Exception as e:
            raise Exception(f"ピッキングリスト生成エラー: {str(e)}")
    
    def execute_antique_register(self):
        """古物台帳生成の実行"""
        try:
            # ダミーデータで古物台帳生成
            result = self.api_client.antique_register_generate("2025-01-01", "2025-01-31")
            
            # 進捗更新
            for i in range(10):
                if self.should_stop:
                    break
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)
                time.sleep(0.2)
                self.progress_updated.emit(int((i + 1) / 10 * 100))
                
        except Exception as e:
            raise Exception(f"古物台帳生成エラー: {str(e)}")
    
    def pause_workflow(self):
        """ワークフローの一時停止"""
        self.is_paused = True
        
    def resume_workflow(self):
        """ワークフローの再開"""
        self.is_paused = False
        
    def stop_workflow(self):
        """ワークフローの停止"""
        self.should_stop = True


class WorkflowPanel(QWidget):
    """ワークフローパネル"""
    
    # シグナル定義
    workflow_started = Signal()
    workflow_completed = Signal()
    workflow_paused = Signal()
    workflow_resumed = Signal()
    workflow_stopped = Signal()
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.workflow_worker = None
        self.steps = []
        self.current_step = -1
        
        # ワークフローステップの初期化
        self.setup_workflow_steps()
        
        # UIの初期化
        self.setup_ui()
        
    def setup_workflow_steps(self):
        """ワークフローステップの設定"""
        self.steps = [
            WorkflowStep(0, "1. 仕入データ取込", "CSVファイルから仕入データを読み込み"),
            WorkflowStep(1, "2. SKU生成", "商品にSKUを自動生成・重複チェック"),
            WorkflowStep(2, "3. 出品CSV生成", "プライスター形式の出品CSVを生成"),
            WorkflowStep(3, "4. ピッキングリスト生成", "倉庫作業用ピッキングリストを生成"),
            WorkflowStep(4, "5. 古物台帳生成", "法定要件に準拠した古物台帳を生成")
        ]
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # ワークフロー表示エリア
        self.setup_workflow_display()
        
        # 進捗表示エリア
        self.setup_progress_display()
        
        # コントロールボタンエリア
        self.setup_control_buttons()
        
    def setup_workflow_display(self):
        """ワークフロー表示エリアの設定"""
        workflow_group = QGroupBox("作業フロー")
        workflow_layout = QVBoxLayout(workflow_group)
        
        # ステップ表示
        self.step_widgets = []
        for i, step in enumerate(self.steps):
            step_widget = self.create_step_widget(i, step)
            self.step_widgets.append(step_widget)
            workflow_layout.addWidget(step_widget['frame'])  # フレームを追加
        
        self.layout().addWidget(workflow_group)
        
    def create_step_widget(self, index, step):
        """ステップウィジェットの作成"""
        step_frame = QFrame()
        step_frame.setFrameStyle(QFrame.Box)
        step_frame.setLineWidth(1)
        step_layout = QHBoxLayout(step_frame)
        
        # ステップ番号
        step_number = QLabel(str(index + 1))
        step_number.setFont(QFont("", 12, QFont.Bold))
        step_number.setMinimumWidth(30)
        step_number.setAlignment(Qt.AlignCenter)
        step_layout.addWidget(step_number)
        
        # ステップ名
        step_name = QLabel(step.name)
        step_name.setFont(QFont("", 10, QFont.Bold))
        step_layout.addWidget(step_name)
        
        # ステップ説明
        step_desc = QLabel(step.description)
        step_desc.setStyleSheet("color: #666666;")
        step_layout.addWidget(step_desc)
        
        # ステップ状態
        step_status = QLabel("待機中")
        step_status.setMinimumWidth(60)
        step_status.setAlignment(Qt.AlignCenter)
        step_layout.addWidget(step_status)
        
        # ステップウィジェットの保存
        step_widget = {
            'frame': step_frame,
            'number': step_number,
            'name': step_name,
            'desc': step_desc,
            'status': step_status
        }
        
        return step_widget
        
    def setup_progress_display(self):
        """進捗表示エリアの設定"""
        progress_group = QGroupBox("進捗状況")
        progress_layout = QVBoxLayout(progress_group)
        
        # 全体進捗バー
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        progress_layout.addWidget(self.overall_progress)
        
        # 現在ステップ進捗バー
        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        self.current_progress.setValue(0)
        progress_layout.addWidget(self.current_progress)
        
        # 進捗ラベル
        self.progress_label = QLabel("準備完了")
        self.progress_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.progress_label)
        
        self.layout().addWidget(progress_group)
        
    def setup_control_buttons(self):
        """コントロールボタンエリアの設定"""
        control_group = QGroupBox("一括実行コントロール")
        control_layout = QHBoxLayout(control_group)
        
        # 全自動実行ボタン
        self.start_btn = QPushButton("全自動実行")
        self.start_btn.clicked.connect(self.start_workflow)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        control_layout.addWidget(self.start_btn)
        
        # 一時停止ボタン
        self.pause_btn = QPushButton("一時停止")
        self.pause_btn.clicked.connect(self.pause_workflow)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: black;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e0a800;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        control_layout.addWidget(self.pause_btn)
        
        # リセットボタン
        self.reset_btn = QPushButton("リセット")
        self.reset_btn.clicked.connect(self.reset_workflow)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        control_layout.addWidget(self.reset_btn)
        
        control_layout.addStretch()
        
        # 実行時間表示
        self.execution_time_label = QLabel("実行時間: 00:00")
        control_layout.addWidget(self.execution_time_label)
        
        self.layout().addWidget(control_group)
        
    def start_workflow(self):
        """ワークフローの開始"""
        if self.workflow_worker and self.workflow_worker.isRunning():
            QMessageBox.warning(self, "警告", "ワークフローが既に実行中です")
            return
            
        # ワークフローワーカーの作成
        self.workflow_worker = WorkflowWorker(self.steps, self.api_client)
        self.workflow_worker.step_started.connect(self.on_step_started)
        self.workflow_worker.step_completed.connect(self.on_step_completed)
        self.workflow_worker.progress_updated.connect(self.on_progress_updated)
        self.workflow_worker.workflow_completed.connect(self.on_workflow_completed)
        self.workflow_worker.error_occurred.connect(self.on_workflow_error)
        
        # ボタンの状態更新
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        
        # ワークフローの開始
        self.workflow_worker.start()
        self.workflow_started.emit()
        
        # 実行時間の計測開始
        self.start_time = time.time()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_execution_time)
        self.timer.start(1000)  # 1秒間隔
        
    def pause_workflow(self):
        """ワークフローの一時停止"""
        if self.workflow_worker and self.workflow_worker.isRunning():
            if self.workflow_worker.is_paused:
                # 再開
                self.workflow_worker.resume_workflow()
                self.pause_btn.setText("一時停止")
                self.progress_label.setText("実行中...")
                self.workflow_resumed.emit()
            else:
                # 一時停止
                self.workflow_worker.pause_workflow()
                self.pause_btn.setText("再開")
                self.progress_label.setText("一時停止中...")
                self.workflow_paused.emit()
                
    def reset_workflow(self):
        """ワークフローのリセット"""
        # ワークフローの停止
        if self.workflow_worker and self.workflow_worker.isRunning():
            self.workflow_worker.stop_workflow()
            self.workflow_worker.wait()
            
        # タイマーの停止
        if hasattr(self, 'timer'):
            self.timer.stop()
            
        # 状態のリセット
        self.reset_workflow_state()
        self.workflow_stopped.emit()
        
    def reset_workflow_state(self):
        """ワークフロー状態のリセット"""
        # ステップ状態のリセット
        for i, step_widget in enumerate(self.step_widgets):
            step_widget['status'].setText("待機中")
            step_widget['frame'].setStyleSheet("")
            
        # 進捗バーのリセット
        self.overall_progress.setValue(0)
        self.current_progress.setValue(0)
        self.progress_label.setText("準備完了")
        
        # ボタンの状態リセット
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("一時停止")
        self.reset_btn.setEnabled(False)
        
        # 実行時間のリセット
        self.execution_time_label.setText("実行時間: 00:00")
        
    def on_step_started(self, step_index, step_name):
        """ステップ開始時の処理"""
        self.current_step = step_index
        
        # ステップウィジェットの更新
        step_widget = self.step_widgets[step_index]
        step_widget['status'].setText("実行中")
        step_widget['frame'].setStyleSheet("background-color: #fff3cd; border: 2px solid #ffc107;")
        
        # 進捗ラベルの更新
        self.progress_label.setText(f"実行中: {step_name}")
        
    def on_step_completed(self, step_index, step_name):
        """ステップ完了時の処理"""
        # ステップウィジェットの更新
        step_widget = self.step_widgets[step_index]
        step_widget['status'].setText("完了")
        step_widget['frame'].setStyleSheet("background-color: #d4edda; border: 2px solid #28a745;")
        
        # 全体進捗の更新
        overall_progress = int((step_index + 1) / len(self.steps) * 100)
        self.overall_progress.setValue(overall_progress)
        
        # 現在ステップ進捗のリセット
        self.current_progress.setValue(0)
        
    def on_progress_updated(self, progress):
        """進捗更新時の処理"""
        self.current_progress.setValue(progress)
        
    def on_workflow_completed(self):
        """ワークフロー完了時の処理"""
        # タイマーの停止
        if hasattr(self, 'timer'):
            self.timer.stop()
            
        # ボタンの状態更新
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        
        # 進捗ラベルの更新
        self.progress_label.setText("ワークフロー完了")
        
        # 完了メッセージ
        QMessageBox.information(self, "完了", "ワークフローが正常に完了しました")
        
        self.workflow_completed.emit()
        
    def on_workflow_error(self, error_message):
        """ワークフローエラー時の処理"""
        # タイマーの停止
        if hasattr(self, 'timer'):
            self.timer.stop()
            
        # ボタンの状態更新
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        
        # エラーメッセージ
        QMessageBox.critical(self, "エラー", f"ワークフローでエラーが発生しました:\n{error_message}")
        
    def update_execution_time(self):
        """実行時間の更新"""
        if hasattr(self, 'start_time'):
            elapsed_time = time.time() - self.start_time
            minutes = int(elapsed_time // 60)
            seconds = int(elapsed_time % 60)
            self.execution_time_label.setText(f"実行時間: {minutes:02d}:{seconds:02d}")
