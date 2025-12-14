#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像背景削除サービス

rembg ライブラリを使用して商品画像の背景を透明化（白抜き）する。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ImageBackgroundRemovalService:
    """画像背景削除サービス（rembg使用）"""

    @staticmethod
    def is_available() -> tuple[bool, str]:
        """rembg ライブラリが利用可能かチェック
        
        Returns:
            (利用可能か, エラーメッセージ or バージョン情報)
        """
        try:
            import rembg  # type: ignore
            import sys
            # バージョン情報とPythonパスを取得
            version = getattr(rembg, '__version__', 'unknown')
            python_path = sys.executable
            
            # 実際に remove 関数をインポートできるかテスト（依存関係チェック）
            try:
                from rembg import remove  # type: ignore
            except ImportError as dep_error:
                # rembgはインストールされているが、依存関係が不足している
                return False, (
                    f"rembg {version} はインストールされていますが、\n"
                    f"依存関係のインポートに失敗しました: {dep_error}\n\n"
                    f"解決方法:\n"
                    f"以下のコマンドで依存関係をインストールしてください:\n"
                    f"{python_path} -m pip install onnxruntime\n\n"
                    f"使用中のPython: {python_path}"
                )
            
            return True, f"rembg {version} (Python: {python_path})"
        except ImportError as e:
            import sys
            python_path = sys.executable
            return False, f"rembgのインポートに失敗: {e}\n使用中のPython: {python_path}"

    @staticmethod
    def remove_background(
        input_path: str,
        output_path: Optional[str] = None,
        model_name: str = "u2net"
    ) -> Optional[str]:
        """画像の背景を削除して透明化する

        Args:
            input_path: 入力画像ファイルパス
            output_path: 出力画像ファイルパス（Noneの場合は自動生成）
            model_name: rembgのモデル名（デフォルト: "u2net"）

        Returns:
            出力ファイルパス（成功時）、None（失敗時）

        Raises:
            RuntimeError: rembgがインストールされていない、または処理に失敗した場合
        """
        available, info = ImageBackgroundRemovalService.is_available()
        if not available:
            raise RuntimeError(
                f"rembg ライブラリが見つかりません。\n\n"
                f"{info}\n\n"
                f"解決方法:\n"
                f"1. アプリが使用しているPython環境で rembg をインストールしてください\n"
                f"2. ターミナルで以下のコマンドを実行:\n"
                f"   {sys.executable} -m pip install rembg\n"
                f"3. アプリを再起動してください"
            )

        try:
            from rembg import remove, new_session  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError as e:
            raise RuntimeError(f"必要なライブラリのインポートに失敗しました: {e}") from e

        input_path_obj = Path(input_path)
        if not input_path_obj.exists():
            raise FileNotFoundError(f"入力画像が見つかりません: {input_path}")

        # 出力パスが指定されていない場合は自動生成
        if output_path is None:
            output_dir = input_path_obj.parent
            output_name = input_path_obj.stem + "_白抜き.png"
            output_path = str(output_dir / output_name)
        else:
            output_path_obj = Path(output_path)
            # 出力ディレクトリが存在しない場合は作成
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 画像を読み込み
            with open(input_path, "rb") as input_file:
                input_data = input_file.read()

            # 新しいrembgバージョンでは、new_session()でセッションを作成してから使用
            session = new_session(model_name)
            # 背景削除処理（session引数として渡す）
            output_data = remove(input_data, session=session)

            # 結果を保存
            with open(output_path, "wb") as output_file:
                output_file.write(output_data)

            logger.info(f"背景削除完了: {input_path} -> {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"背景削除エラー: {input_path}, エラー: {e}")
            raise RuntimeError(f"背景削除処理に失敗しました: {e}") from e




