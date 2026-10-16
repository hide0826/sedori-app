#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI 接続テストのURL順と、失敗時の説明。"""
from desktop.api.client import health_check_urls
from desktop.utils.api_test_helper import explain_api_error, test_fastapi_connection


def test_localhost_tries_ipv4_first():
    urls = health_check_urls("http://localhost:8000")
    assert urls[0] == "http://127.0.0.1:8000"
    assert "http://localhost:8000" in urls


def test_ipv4_also_tries_localhost():
    urls = health_check_urls("http://127.0.0.1:8000/")
    assert urls[0] == "http://127.0.0.1:8000"
    assert urls[1] == "http://localhost:8000"


def test_blank_url_defaults_to_ipv4():
    urls = health_check_urls("  ")
    assert urls[0] == "http://127.0.0.1:8000"
    assert "http://localhost:8000" in urls


def test_timeout_message_tells_user_to_restart():
    text = explain_api_error(
        "fastapi",
        "Read timed out",
        url="http://localhost:8000",
    )
    assert "起動し直して" in text
    assert "http://localhost:8000" in text


class _Client:
    def __init__(self, ok: bool, error: str = ""):
        self.last_connection_error = error
        self.ok = ok

    def test_connection(self) -> bool:
        return self.ok


def test_failure_includes_real_error():
    client = _Client(False, "http://127.0.0.1:8000/health → Read timed out")
    result = test_fastapi_connection("http://localhost:8000", test_fn=client.test_connection)
    assert result.success is False
    assert "Read timed out" in result.details
    assert "起動し直して" in result.details
