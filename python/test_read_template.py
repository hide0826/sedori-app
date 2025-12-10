#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.amazon_inventory_loader_service import AmazonInventoryLoaderService

template_path = r"D:\HIRIO\repo\sedori-app.github\python\ListingLoader.xlsm"

output_lines = []

def log(msg):
    output_lines.append(msg)
    print(msg)
    sys.stdout.flush()

try:
    log("=== Amazon Template Excel Analysis ===")
    log(f"\nReading template file: {template_path}")
    
    result = AmazonInventoryLoaderService.read_amazon_template_excel(template_path)
    
    log(f"\nAvailable sheets: {result['sheet_names']}")
    
    if result["template_sheet"]:
        ts = result["template_sheet"]
        log(f"\nTemplate Sheet:")
        log(f"  Max row: {ts['max_row']}")
        log(f"  Max column: {ts['max_column']}")
        log(f"\nHeaders:")
        for col_idx, header in ts["headers"]:
            log(f"  Column {col_idx}: {header}")
    else:
        log("\nTemplate sheet not found!")
    
    # 結果をファイルに保存
    output_file = Path(__file__).parent / "template_read_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    log(f"\nResults saved to: {output_file}")
        
except Exception as e:
    log(f"Error: {e}")
    import traceback
    traceback.print_exc()
    # エラーもファイルに保存
    output_file = Path(__file__).parent / "template_read_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
        f.write("\n\nTraceback:\n")
        f.write(traceback.format_exc())




