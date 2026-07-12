#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DB × 価格改定まわりの utils import 互換レイヤー。

デスクトップ実行時は ``utils.*`` → ``desktop/utils``、
pytest（``python/`` 起点）時は ``desktop.utils.*`` へフォールバックする。
"""

from __future__ import annotations

try:
    from utils.purchase_elapsed_days import (
        calc_elapsed_days_for_purchase_record,
        format_elapsed_days_for_purchase_record,
    )
    from utils.settings_helper import get_amazon_fba_simulator_url
    from utils.repricer_ladder_table import (
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        build_ladder_rules_with_standard_trace,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )
except ImportError:
    from desktop.utils.purchase_elapsed_days import (  # type: ignore
        calc_elapsed_days_for_purchase_record,
        format_elapsed_days_for_purchase_record,
    )
    from desktop.utils.settings_helper import get_amazon_fba_simulator_url  # type: ignore
    from desktop.utils.repricer_ladder_table import (  # type: ignore
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        build_ladder_rules_with_standard_trace,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )

__all__ = [
    "calc_elapsed_days_for_purchase_record",
    "format_elapsed_days_for_purchase_record",
    "get_amazon_fba_simulator_url",
    "apply_even_margin_descent_to_ladder_table",
    "apply_ladder_rules_to_table",
    "apply_ladder_row_elapsed_lock",
    "build_ladder_rules_with_standard_trace",
    "collect_ladder_rules_from_table",
    "create_ladder_rules_table",
    "ladder_rules_to_json",
    "load_reprice_config_for_template",
    "margin_percent_from_target_price",
    "parse_ladder_rules_json",
    "populate_ladder_table_rows",
    "set_ladder_table_profit_context",
    "template_rules_from_default_profile",
    "update_ladder_profit_labels",
]
