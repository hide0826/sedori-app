#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.amazon_inventory_loader_service import AmazonInventoryLoaderService

template_path = Path(__file__).parent / "ListingLoader.xlsm"

result_text = []

try:
    result = AmazonInventoryLoaderService.read_amazon_template_excel(str(template_path))
    
    result_text.append("=== Amazon Template Excel Analysis ===")
    result_text.append(f"\nFile: {template_path}")
    result_text.append(f"Available sheets: {result['sheet_names']}")
    
    if result["template_sheet"]:
        ts = result["template_sheet"]
        result_text.append(f"\n✓ Template Sheet Found!")
        result_text.append(f"  Max row: {ts['max_row']}")
        result_text.append(f"  Max column: {ts['max_column']}")
        result_text.append(f"\nHeaders ({len(ts['headers'])} columns):")
        for col_idx, header in ts["headers"]:
            result_text.append(f"  Column {col_idx}: {header}")
    else:
        result_text.append("\n✗ Template sheet not found!")
    
    output = "\n".join(result_text)
    print(output)
    
    # ファイルに保存
    output_file = Path(__file__).parent / "template_check_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n✓ Results saved to: {output_file}")
    
except Exception as e:
    error_msg = f"Error: {type(e).__name__}: {e}"
    print(error_msg)
    import traceback
    traceback.print_exc()
    
    output_file = Path(__file__).parent / "template_check_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(error_msg + "\n")
        f.write(traceback.format_exc())





