#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from services.amazon_inventory_loader_service import AmazonInventoryLoaderService
    
    template_path = str(Path(__file__).parent / "ListingLoader.xlsm")
    
    print(f"Reading template: {template_path}")
    result = AmazonInventoryLoaderService.read_amazon_template_excel(template_path)
    
    # JSON形式で保存
    output_json = Path(__file__).parent / "template_result.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # テキスト形式でも保存
    output_txt = Path(__file__).parent / "template_result.txt"
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("=== Amazon Template Excel Analysis ===\n\n")
        f.write(f"File: {template_path}\n")
        f.write(f"Available sheets: {result['sheet_names']}\n\n")
        
        if result["template_sheet"]:
            ts = result["template_sheet"]
            f.write("✓ Template Sheet Found!\n")
            f.write(f"  Max row: {ts['max_row']}\n")
            f.write(f"  Max column: {ts['max_column']}\n\n")
            f.write(f"Headers ({len(ts['headers'])} columns):\n")
            for col_idx, header in ts["headers"]:
                f.write(f"  Column {col_idx}: {header}\n")
        else:
            f.write("✗ Template sheet not found!\n")
    
    print("✓ Success! Results saved to:")
    print(f"  - {output_json}")
    print(f"  - {output_txt}")
    
except Exception as e:
    error_file = Path(__file__).parent / "template_error.txt"
    with open(error_file, "w", encoding="utf-8") as f:
        f.write(f"Error: {type(e).__name__}: {e}\n")
        import traceback
        f.write(traceback.format_exc())
    print(f"✗ Error: {e}")
    print(f"Details saved to: {error_file}")
    sys.exit(1)








