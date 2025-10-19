#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import io

# UTF-8でコンソール出力を強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, 'D:/HIRIO/repo/sedori-app.github')
from core.csv_utils import normalize_string_for_cp932

# テストケース
test_cases = [
    ('通常の日本語', '通常の日本語'),
    ('emダッシュ—test', 'emダッシュ-test'),
    ('enダッシュ–test', 'enダッシュ-test'),
    ('左クォート"test"', '左クォート"test"'),
    ('三点リーダー…', '三点リーダー...'),
    ('全角チルダ～test', '全角チルダ~test'),
    ('星★ハート♡', '星*ハート(heart)'),
    ('矢印→←↑↓', '矢印-><-^v'),
    ('【新品】《限定》', '[新品]<<限定>>'),
    ('温度25℃と77℉', '温度25Cと77F'),
    ('数式±×÷≒', '数式+/-x/='),
]

print('=== CP932 Normalization Test ===\n')
success_count = 0
fail_count = 0

for original, expected_pattern in test_cases:
    normalized = normalize_string_for_cp932(original)

    # CP932エンコード可能性テスト
    try:
        encoded = normalized.encode('cp932')
        can_encode = True
        encode_status = 'OK'
    except UnicodeEncodeError as e:
        can_encode = False
        encode_status = f'FAIL: {e}'

    # 結果表示
    status = 'PASS' if can_encode else 'FAIL'
    if can_encode:
        success_count += 1
    else:
        fail_count += 1

    print(f'[{status}] Original: {original}')
    print(f'      Normalized: {normalized}')
    print(f'      CP932 Encode: {encode_status}')
    print()

print(f'=== Summary ===')
print(f'Success: {success_count}/{len(test_cases)}')
print(f'Failed: {fail_count}/{len(test_cases)}')
