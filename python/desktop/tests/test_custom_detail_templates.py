#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""詳細説明カスタム行（customN）のヘルパー試験。"""

from __future__ import annotations

from desktop.ui.inventory.support import (
    checked_detail_description,
    default_custom_template_label,
    list_custom_template_keys,
    next_custom_template_key,
)


def test_list_custom_template_keys_defaults():
    assert list_custom_template_keys({}, ensure_defaults=True) == [
        "custom1",
        "custom2",
        "custom3",
    ]
    assert list_custom_template_keys({}, ensure_defaults=False) == []


def test_list_custom_template_keys_unlimited():
    data = {
        "custom_labels": {"custom1": "A", "custom5": "E"},
        "keywords": {"custom2": "text", "取説欠品": "x"},
    }
    assert list_custom_template_keys(data) == ["custom1", "custom2", "custom5"]


def test_next_custom_template_key():
    assert next_custom_template_key([]) == "custom1"
    assert next_custom_template_key(["custom1", "custom2", "custom3"]) == "custom4"
    assert next_custom_template_key(["custom1", "custom5"]) == "custom6"


def test_default_custom_template_label():
    assert default_custom_template_label("custom4") == "カスタム4"


def test_checked_detail_description_custom_flags():
    keywords = {
        "custom1": "文1",
        "custom4": "文4",
    }
    text = checked_detail_description(
        keywords,
        manual=False,
        inner_box=False,
        custom_flags={"custom1": True, "custom4": True},
    )
    assert text == "文1\n文4"

    assert (
        checked_detail_description(
            keywords,
            manual=False,
            inner_box=False,
            custom_flags={"custom4": False},
        )
        is None
    )
