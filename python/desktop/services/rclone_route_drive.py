# -*- coding: utf-8 -*-
"""Webテンプレ作成後に rclone で Google Drive 上へルート箱を作る／送る。

mount は使わない。`rclone mkdir` + `rclone copy --create-empty-src-dirs`。
未設定・未導入時はスキップ（Webテンプレ自体は成功扱い）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# リポジトリ直下 config/rclone_route_drive.json
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "rclone_route_drive.json"
_EXAMPLE_CONFIG_PATH = _REPO_ROOT / "config" / "rclone_route_drive.example.json"


@dataclass
class RclonePushResult:
    status: str  # ok | skipped | error
    message: str
    remote_path: str = ""


def _env_truthy(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def load_rclone_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """設定ファイル＋環境変数。env が優先。"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    data: Dict[str, Any] = {
        "enabled": False,
        "rclone_exe": "rclone",
        "remote": "",
        "remote_root": "せどり総合/店舗せどり仕入リスト入れ/仕入帳",
        "timeout_sec": 180,
    }
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception as exc:
            print(f"rclone_route_drive.json 読込失敗: {exc}")

    env_enabled = _env_truthy("HIRIO_RCLONE_ENABLED")
    if env_enabled is not None:
        data["enabled"] = env_enabled
    if os.environ.get("HIRIO_RCLONE_EXE"):
        data["rclone_exe"] = os.environ["HIRIO_RCLONE_EXE"].strip()
    if os.environ.get("HIRIO_RCLONE_REMOTE"):
        data["remote"] = os.environ["HIRIO_RCLONE_REMOTE"].strip()
    if os.environ.get("HIRIO_RCLONE_ROUTE_ROOT"):
        data["remote_root"] = os.environ["HIRIO_RCLONE_ROUTE_ROOT"].strip()
    return data


def find_rclone_exe(preferred: str = "rclone") -> Optional[str]:
    """PATH またはよくある配置から rclone を探す。

    GUI 起動の HIRIO は PowerShell と PATH が違うことがあるため、
    WinGet の Links / Packages も明示的に探す。
    """
    if preferred and preferred not in ("rclone", "rclone.exe"):
        p = Path(preferred)
        if p.is_file():
            return str(p.resolve())

    which = shutil.which(preferred) or shutil.which("rclone") or shutil.which("rclone.exe")
    if which:
        return str(Path(which).resolve())

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    user_profile = Path(os.environ.get("USERPROFILE", ""))
    candidates: List[Path] = [
        local / "Microsoft" / "WinGet" / "Links" / "rclone.exe",
        local / "rclone" / "rclone.exe",
        user_profile / "scoop" / "shims" / "rclone.exe",
        Path(r"C:\Program Files\rclone\rclone.exe"),
        Path(r"C:\rclone\rclone.exe"),
        _REPO_ROOT / "tools" / "rclone" / "rclone.exe",
        Path(r"C:\HIRIO\tools\rclone\rclone.exe"),
    ]
    # WinGet Packages 配下（バージョン付きフォルダ）
    winget_pkgs = local / "Microsoft" / "WinGet" / "Packages"
    if winget_pkgs.is_dir():
        try:
            for hit in sorted(winget_pkgs.glob("Rclone.Rclone*/rclone*/rclone.exe"), reverse=True):
                candidates.append(hit)
            for hit in sorted(winget_pkgs.glob("**/rclone.exe"), reverse=True):
                if hit not in candidates:
                    candidates.append(hit)
        except OSError:
            pass

    for p in candidates:
        try:
            if p.is_file():
                return str(p.resolve())
        except OSError:
            continue
    return None


def remote_dest(remote: str, remote_root: str, folder_name: str) -> str:
    """gdrive:せどり…/仕入帳/20260922鎌倉 形式。"""
    remote = (remote or "").strip().rstrip(":")
    root = (remote_root or "").strip().strip("/").strip("\\")
    name = (folder_name or "").strip().strip("/").strip("\\")
    if root:
        return f"{remote}:{root}/{name}"
    return f"{remote}:{name}"


def _run(
    exe: str,
    args: List[str],
    *,
    timeout_sec: int = 180,
) -> Tuple[int, str, str]:
    cmd = [exe, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout_sec}s"
    except OSError as exc:
        return 127, "", str(exc)


def push_route_folder_to_drive(
    local_folder: Path,
    *,
    config_path: Optional[Path] = None,
) -> RclonePushResult:
    """ローカルルート箱を Drive 上の remote_root/箱名 へ copy。

    mkdir は省略（copy が親パスを作る）。UI を止めないよう呼び出し側で
    バックグラウンド実行すること。
    """
    cfg = load_rclone_config(config_path)
    if not cfg.get("enabled"):
        return RclonePushResult(
            "skipped",
            "rclone Drive 連携は無効です（config/rclone_route_drive.json の enabled か HIRIO_RCLONE_ENABLED）",
        )

    remote = str(cfg.get("remote") or "").strip()
    if not remote:
        return RclonePushResult(
            "skipped",
            "rclone remote 未設定（remote または HIRIO_RCLONE_REMOTE）",
        )

    local = Path(local_folder)
    if not local.is_dir():
        return RclonePushResult("error", f"ローカル箱がありません: {local}")

    exe = find_rclone_exe(str(cfg.get("rclone_exe") or "rclone"))
    if not exe:
        return RclonePushResult(
            "skipped",
            "rclone が見つかりません（PATH か tools/rclone/rclone.exe）。導入後に再実行してください",
        )

    timeout = int(cfg.get("timeout_sec") or 180)
    remote_root = str(cfg.get("remote_root") or "").strip()
    dest = remote_dest(remote, remote_root, local.name)

    # mkdir は Google Drive API で固まりやすいので省略。copy がディレクトリを作る。
    code, out, err = _run(
        exe,
        [
            "copy",
            str(local),
            dest,
            "--create-empty-src-dirs",
            "--transfers",
            "4",
            "--checkers",
            "8",
            "--retries",
            "2",
            "--low-level-retries",
            "3",
            "--contimeout",
            "20s",
            "--timeout",
            "60s",
        ],
        timeout_sec=timeout,
    )
    if code != 0:
        detail = (err or out or "").strip() or f"exit={code}"
        return RclonePushResult("error", f"rclone copy 失敗: {detail}", remote_path=dest)

    return RclonePushResult(
        "ok",
        f"Drive へ送信しました: {dest}",
        remote_path=dest,
    )


def config_help_text() -> str:
    example = _EXAMPLE_CONFIG_PATH
    return (
        "rclone Drive 連携の準備:\n"
        f"1. rclone を導入（例: winget install Rclone.Rclone）\n"
        "2. rclone config で Google Drive リモートを作る（例: 名前 gdrive）\n"
        f"3. {example.name} を rclone_route_drive.json にコピーして enabled/remote を設定\n"
        "   または環境変数 HIRIO_RCLONE_ENABLED=1 と HIRIO_RCLONE_REMOTE=gdrive"
    )
