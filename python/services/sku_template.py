from __future__ import annotations

import re
import json
from datetime import datetime
from typing import Dict, Any, Optional


COND_NUM_MAP = {
    "新品": 11,
    "新品(新品)": 11,
    "中古(ほぼ新品)": 1,
    "中古(非常に良い)": 2,
    "中古(良い)": 3,
    "中古(可)": 4,
}

COND_CODE_MAP = {
    "新品": "new",
    "新品(新品)": "new",
    "中古(ほぼ新品)": "used1",
    "中古(非常に良い)": "used2",
    "中古(良い)": "used3",
    "中古(可)": "used4",
}


class SKUTemplateRenderer:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings or {}
        self.template: str = self.settings.get(
            "skuTemplate",
            "{date:YYYYMMDD}-{ASIN|JAN}-{supplier}-{seq:3}-{condNum}",
        )
        self.seq_scope: str = self.settings.get("seqScope", "day")
        self.seq_start: int = int(self.settings.get("seqStart", 1))
        self.date_cache: Optional[str] = None

    def _today(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _get_cond_num(self, condition: str) -> Optional[int]:
        return COND_NUM_MAP.get(condition)

    def _get_cond_code(self, condition: str) -> Optional[str]:
        return COND_CODE_MAP.get(condition)

    def _choose_asin_jan(self, p: Dict[str, Any]) -> str:
        asin = p.get("asin") or p.get("ASIN") or ""
        jan = p.get("jan") or p.get("JAN") or ""
        return asin or jan

    def _sanitize(self, s: str) -> str:
        # 許可: 英数・ハイフン・アンダースコア
        s = re.sub(r"[^0-9A-Za-z\-_]", "-", s)
        s = re.sub(r"-+", "-", s)
        s = s.strip("-")
        return s[:60]

    def _resolve_token(self, token: str, p: Dict[str, Any], seq_value: int) -> str:
        # {date[:FMT]}
        if token.startswith("date"):
            parts = token.split(":")
            fmt = parts[1] if len(parts) > 1 else "YYYYMMDD"
            fmt_py = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
            return datetime.now().strftime(fmt_py)

        # {ASIN|JAN} or {asin}/{jan}
        if token in ("ASIN|JAN", "ASIN_JAN"):
            return self._choose_asin_jan(p)
        if token.lower() == "asin":
            return str(p.get("asin") or p.get("ASIN") or "")
        if token.lower() == "jan":
            return str(p.get("jan") or p.get("JAN") or "")

        # {condNum} / {condCode}
        if token == "condNum":
            c = p.get("condition") or p.get("コンディション", "")
            v = self._get_cond_num(c)
            return str(v) if v is not None else ""
        if token == "condCode":
            c = p.get("condition") or p.get("コンディション", "")
            v = self._get_cond_code(c)
            return v or ""

        # {ship}
        if token == "ship":
            return str(p.get("shippingMethod") or p.get("発送方法") or "")

        # {supplier}
        if token == "supplier":
            return str(p.get("supplier_code") or p.get("仕入先") or p.get("supplier") or "")

        # {seq[:digits][:scope]}
        if token.startswith("seq"):
            # seq:3 or seq:4:day
            parts = token.split(":")
            width = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
            return str(seq_value).zfill(width)

        # {custom:XXX} / {text:XXX}
        if token.startswith("custom:") or token.startswith("text:"):
            return token.split(":", 1)[1]

        return ""

    def render_sku(self, product: Dict[str, Any], seq_offset: int = 0) -> str:
        # 連番（スコープdayのみサポート。seqStart + offset）
        base = int(self.seq_start)
        seq_value = base + seq_offset

        # {ASIN|JAN} の短縮表記に対応: {ASIN|JAN} or {asin} {jan}
        tpl = self.template.replace("{ASIN|JAN}", "{ASIN|JAN}")

        tokens = re.findall(r"\{([^{}]+)\}", tpl)
        out_parts = []
        last_idx = 0
        for m in re.finditer(r"\{([^{}]+)\}", tpl):
            out_parts.append(tpl[last_idx:m.start()])
            token_inner = m.group(1)
            out = self._resolve_token(token_inner, product, seq_value)
            if out:
                out_parts.append(out)
            last_idx = m.end()
        out_parts.append(tpl[last_idx:])

        sku_raw = "".join(out_parts)
        return self._sanitize(sku_raw)







