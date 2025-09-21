from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "tmp"
TMP_DIR.mkdir(exist_ok=True)
