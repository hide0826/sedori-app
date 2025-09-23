import pathlib

# This file's path: D:/HIRIO/repo/sedori-app.github/python/core/config.py
# We want BASE_DIR to be D:/HIRIO/repo/sedori-app.github
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "reprice_rules.json"