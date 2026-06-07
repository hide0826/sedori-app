#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolve_maps_api_key の単体テスト"""

import os
import sys

# テスト用に QSettings をモックする前に import
sys.path.insert(0, os.path.dirname(__file__))

from google_maps_service import resolve_maps_api_key


def test_explicit_key():
    assert resolve_maps_api_key("  explicit-key  ") == "explicit-key"


def test_empty_explicit():
    assert resolve_maps_api_key("   ") is None


if __name__ == "__main__":
    test_explicit_key()
    test_empty_explicit()
    print("resolve_maps_api_key basic tests passed.")
