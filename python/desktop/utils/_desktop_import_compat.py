#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
デスクトップアプリ共通の import 互換レイヤー。

デスクトップ実行時は ``services`` / ``ui`` / ``database``（→ desktop 配下）、
pytest（``python/`` 起点）時は ``desktop.*`` へフォールバックする。
"""

from __future__ import annotations

try:
    from services.condition_labels import (
        backfill_condition_label_in_record,
        condition_code_from_value,
        normalize_condition_display,
    )
except ImportError:
    from desktop.services.condition_labels import (  # type: ignore
        backfill_condition_label_in_record,
        condition_code_from_value,
        normalize_condition_display,
    )

try:
    from services.flea_market_record_utils import (
        resolve_local_image_path,
        resolve_record_product_images,
    )
except ImportError:
    from desktop.services.flea_market_record_utils import (  # type: ignore
        resolve_local_image_path,
        resolve_record_product_images,
    )

try:
    from services.purchase_tp_autofill_369 import (
        break_even_price_int_for_record,
        fill_purchase_record_tp_from_369,
        load_369_repricer_config,
        ta_price_from_target_margin_percent,
    )
    from services.repricer_369_presets import TP_SOURCE_AUTO, TP_SOURCE_MANUAL
except ImportError:
    from desktop.services.purchase_tp_autofill_369 import (  # type: ignore
        break_even_price_int_for_record,
        fill_purchase_record_tp_from_369,
        load_369_repricer_config,
        ta_price_from_target_margin_percent,
    )
    from desktop.services.repricer_369_presets import TP_SOURCE_AUTO, TP_SOURCE_MANUAL  # type: ignore

try:
    from services.keepa_service import KeepaService
    from ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog
except ImportError:
    from desktop.services.keepa_service import KeepaService  # type: ignore
    from desktop.ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog  # type: ignore

try:
    from services.purchase_cost_calc import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        augment_purchase_cost_records,
        fee_storage_value,
        is_fee_amount_column,
        read_fee_fields,
    )
    from services.purchase_channel_cost import (
        apply_fee_values_to_record,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        platform_fee_from_sale_price,
    )
except ImportError:
    from desktop.services.purchase_cost_calc import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        augment_purchase_cost_records,
        fee_storage_value,
        is_fee_amount_column,
        read_fee_fields,
    )
    from desktop.services.purchase_channel_cost import (  # type: ignore
        apply_fee_values_to_record,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        platform_fee_from_sale_price,
    )

try:
    from services.purchase_break_even import (
        compute_break_even_for_record,
        should_recompute_break_even,
    )
except ImportError:
    from desktop.services.purchase_break_even import (  # type: ignore
        compute_break_even_for_record,
        should_recompute_break_even,
    )

try:
    from services.purchase_ladder_autofill_batch import (
        apply_monthly_auto_ladder_to_record,
        is_eligible_for_monthly_auto,
    )
except ImportError:
    from desktop.services.purchase_ladder_autofill_batch import (  # type: ignore
        apply_monthly_auto_ladder_to_record,
        is_eligible_for_monthly_auto,
    )

try:
    from services.purchase_inventory_only import (
        backfill_purchase_date_from_sku,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
    )
except ImportError:
    from desktop.services.purchase_inventory_only import (  # type: ignore
        backfill_purchase_date_from_sku,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
    )

try:
    from services.purchase_table_incremental import (
        SCROLL_LOAD_THRESHOLD_PX,
        get_augment_batch_size,
        get_page_size,
        is_incremental_render_enabled,
        purchase_record_purchase_timestamp,
        sort_purchase_records_for_display,
    )
except ImportError:
    from desktop.services.purchase_table_incremental import (  # type: ignore
        SCROLL_LOAD_THRESHOLD_PX,
        get_augment_batch_size,
        get_page_size,
        is_incremental_render_enabled,
        purchase_record_purchase_timestamp,
        sort_purchase_records_for_display,
    )

try:
    from utils.purchase_elapsed_days import calc_elapsed_days_for_purchase_record
    from utils.purchase_repricing_summary import summarize_repricing_row
except ImportError:
    from desktop.utils.purchase_elapsed_days import (  # type: ignore
        calc_elapsed_days_for_purchase_record,
    )
    from desktop.utils.purchase_repricing_summary import summarize_repricing_row  # type: ignore

try:
    from database.purchase_db import PurchaseDatabase
    from database.store_db import StoreDatabase
except ImportError:
    from desktop.database.purchase_db import PurchaseDatabase  # type: ignore
    from desktop.database.store_db import StoreDatabase  # type: ignore

try:
    from services.backup_service import (
        create_backup,
        get_backup_folder,
        list_backup_archives,
        record_backup_success,
        restore_from_zip,
    )
except ImportError:
    from desktop.services.backup_service import (  # type: ignore
        create_backup,
        get_backup_folder,
        list_backup_archives,
        record_backup_success,
        restore_from_zip,
    )

try:
    from services.recording_mode_service import set_recording_mode_enabled
except ImportError:
    from desktop.services.recording_mode_service import set_recording_mode_enabled  # type: ignore

try:
    from services.ocr_service import OCRService
except ImportError:
    from desktop.services.ocr_service import OCRService  # type: ignore

try:
    from utils.settings_helper import (
        DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL,
        DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
        DEFAULT_PRICETAR_LISTING_URL,
        DEFAULT_PRICETAR_REPRICING_URL,
        is_recording_mode,
        set_recording_mode_enabled_flag,
    )
except ImportError:
    from desktop.utils.settings_helper import (  # type: ignore
        DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL,
        DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
        DEFAULT_PRICETAR_LISTING_URL,
        DEFAULT_PRICETAR_REPRICING_URL,
        is_recording_mode,
        set_recording_mode_enabled_flag,
    )

try:
    from utils.api_test_helper import (
        explain_api_error,
        test_fastapi_connection,
        test_gemini_api,
        test_keepa_api,
        test_maps_api,
    )
except ImportError:
    from desktop.utils.api_test_helper import (  # type: ignore
        explain_api_error,
        test_fastapi_connection,
        test_gemini_api,
        test_keepa_api,
        test_maps_api,
    )

try:
    from utils.gemini_model_helper import resolve_gemini_flash_model
except ImportError:
    from desktop.utils.gemini_model_helper import resolve_gemini_flash_model  # type: ignore

__all__ = [
    "COL_PLATFORM_FEE",
    "COL_SHIPPING",
    "COL_TOTAL_COST",
    "DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL",
    "DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL",
    "DEFAULT_PRICETAR_LISTING_URL",
    "DEFAULT_PRICETAR_REPRICING_URL",
    "KeepaOfferDetailDialog",
    "KeepaService",
    "OCRService",
    "PurchaseDatabase",
    "SCROLL_LOAD_THRESHOLD_PX",
    "StoreDatabase",
    "TP_SOURCE_AUTO",
    "TP_SOURCE_MANUAL",
    "apply_fee_values_to_record",
    "apply_monthly_auto_ladder_to_record",
    "augment_purchase_cost_records",
    "backfill_condition_label_in_record",
    "backfill_purchase_date_from_sku",
    "break_even_price_int_for_record",
    "calc_elapsed_days_for_purchase_record",
    "compute_break_even_for_record",
    "condition_code_from_value",
    "create_backup",
    "explain_api_error",
    "fee_storage_value",
    "fill_purchase_record_tp_from_369",
    "flea_fee_rate_percent_for_channel",
    "get_augment_batch_size",
    "get_backup_folder",
    "get_page_size",
    "is_amazon_sales_channel",
    "is_eligible_for_monthly_auto",
    "is_fee_amount_column",
    "is_incremental_render_enabled",
    "is_recording_mode",
    "list_backup_archives",
    "load_369_repricer_config",
    "merge_purchase_history_db_into_display_records",
    "normalize_condition_display",
    "normalize_status_code",
    "platform_fee_from_sale_price",
    "purchase_record_purchase_timestamp",
    "read_fee_fields",
    "record_backup_success",
    "resolve_gemini_flash_model",
    "resolve_local_image_path",
    "resolve_record_product_images",
    "restore_from_zip",
    "set_recording_mode_enabled",
    "set_recording_mode_enabled_flag",
    "should_recompute_break_even",
    "sort_purchase_records_for_display",
    "summarize_repricing_row",
    "ta_price_from_target_margin_percent",
    "test_fastapi_connection",
    "test_gemini_api",
    "test_keepa_api",
    "test_maps_api",
]
