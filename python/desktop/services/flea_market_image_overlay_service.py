#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ出品用: 画像1枚に上下テキスト帯を合成する。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

SquareFitMode = Literal["letterbox", "cover"]

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

Align = Literal["left", "center", "right"]

_BAND_MAX_HEIGHT_RATIO_AUTO = 0.18
_BAND_MAX_HEIGHT_RATIO_MANUAL = 0.40
_DEFAULT_TEXT_RGB = (0, 0, 0)
_DEFAULT_BG_RGB = (255, 255, 255)
_DEFAULT_BG_OPACITY_PERCENT = 75
DEFAULT_BOTTOM_EDGE_INSET = 48
_BOTTOM_INSET_MIN_PX = 44
_BOTTOM_INSET_MIN_HEIGHT_RATIO = 0.04
_BOTTOM_BAND_INNER_PAD_RATIO = 0.35
_MIN_FONT_SIZE = 10
_MAX_FONT_SIZE_CAP = 120
_HORIZONTAL_PAD_RATIO = 0.04
_VERTICAL_PAD_RATIO = 0.12
_LINE_SPACING_RATIO = 0.15
_JPEG_QUALITY = 92
DEFAULT_FLEA_SQUARE_SIZE = 1080
MIN_FLEA_SQUARE_SIZE = 600
MAX_FLEA_SQUARE_SIZE = 2048
DEFAULT_SQUARE_FIT_MODE: SquareFitMode = "cover"

SQUARE_FIT_MODE_OPTIONS: Tuple[Tuple[str, SquareFitMode], ...] = (
    ("ズームして1:1に埋める（余白なし）", "cover"),
    ("余白で全体を収める（文字が切れにくい）", "letterbox"),
)


@dataclass
class TextBandStyle:
    """1本のテキスト帯（上部または下部）のスタイル。"""

    text: str = ""
    font_path: Optional[str] = None
    font_size: Optional[int] = None  # None = 自動
    bold: bool = False
    align: Align = "center"
    text_color: Tuple[int, int, int] = field(default_factory=lambda: _DEFAULT_TEXT_RGB)
    bg_color: Tuple[int, int, int] = field(default_factory=lambda: _DEFAULT_BG_RGB)
    bg_opacity_percent: int = _DEFAULT_BG_OPACITY_PERCENT
    edge_inset: int = 0  # 上帯: 上からの余白 / 下帯: 下からの余白（大きいほど上に寄る）

    @property
    def auto_size(self) -> bool:
        return self.font_size is None

    def cache_fragment(self) -> str:
        d = asdict(self)
        d["text_color"] = list(self.text_color)
        d["bg_color"] = list(self.bg_color)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)

    @classmethod
    def default_for_text(cls, text: str) -> "TextBandStyle":
        return cls(text=(text or "").strip())


@dataclass
class ImageOverlaySettings:
    """上下別設定の合成オプション。"""

    top: TextBandStyle = field(default_factory=TextBandStyle)
    bottom: TextBandStyle = field(default_factory=TextBandStyle)
    export_square: bool = True
    square_size: int = DEFAULT_FLEA_SQUARE_SIZE
    square_fit_mode: SquareFitMode = DEFAULT_SQUARE_FIT_MODE
    square_bg_color: Tuple[int, int, int] = field(default_factory=lambda: _DEFAULT_BG_RGB)

    def cache_key(self, source_path: str) -> str:
        square_meta = json.dumps(
            {
                "export_square": self.export_square,
                "square_size": self.square_size,
                "square_fit_mode": self.square_fit_mode,
                "square_bg": list(self.square_bg_color),
            },
            sort_keys=True,
        )
        parts = [
            os.path.normcase(os.path.abspath(source_path)),
            self.top.cache_fragment(),
            self.bottom.cache_fragment(),
            square_meta,
        ]
        return "|".join(parts)

    def has_any_text(self) -> bool:
        return bool((self.top.text or "").strip() or (self.bottom.text or "").strip())


def default_overlay_settings(
    top_text: str = "",
    bottom_text: str = "",
) -> ImageOverlaySettings:
    meiryo = resolve_meiryo_font_path()
    top = TextBandStyle.default_for_text(top_text)
    bottom = TextBandStyle.default_for_text(bottom_text)
    bottom.edge_inset = DEFAULT_BOTTOM_EDGE_INSET
    if meiryo:
        top.font_path = meiryo
        bottom.font_path = meiryo
    return ImageOverlaySettings(top=top, bottom=bottom)


def resolve_meiryo_font_path() -> Optional[str]:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts_dir = Path(windir) / "Fonts"
    for name in ("meiryo.ttc", "Meiryo.ttc", "meiryob.ttc"):
        p = fonts_dir / name
        if p.is_file():
            return str(p)
    return None


def resolve_meiryo_bold_font_path() -> Optional[str]:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts_dir = Path(windir) / "Fonts"
    for name in ("meiryob.ttc", "Meiryo Bold.ttc"):
        p = fonts_dir / name
        if p.is_file():
            return str(p)
    return None


def enumerate_font_choices() -> List[Tuple[str, str]]:
    """(表示名, ファイルパス) のリスト。"""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts_dir = Path(windir) / "Fonts"
    mapping = [
        ("メイリオ", "meiryo.ttc"),
        ("メイリオ 太字", "meiryob.ttc"),
        ("MS ゴシック", "msgothic.ttc"),
        ("MS PGothic", "msgothic.ttc"),
        ("Yu Gothic", "YuGothM.ttc"),
        ("游ゴシック", "yugothm.ttc"),
        ("Meiryo UI", "meiryo.ttc"),
    ]
    seen: set[str] = set()
    out: List[Tuple[str, str]] = []
    for label, fname in mapping:
        p = fonts_dir / fname
        key = str(p.resolve()) if p.is_file() else ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((label, str(p)))
    if not out and resolve_meiryo_font_path():
        out.append(("メイリオ", resolve_meiryo_font_path()))  # type: ignore
    return out


def resolve_font_path_for_style(style: TextBandStyle) -> Optional[str]:
    path = style.font_path or resolve_meiryo_font_path()
    if style.bold and path:
        low = path.lower()
        if "meiryo.ttc" in low and "meiryob" not in low:
            bold = resolve_meiryo_bold_font_path()
            if bold:
                return bold
    return path


def _overlay_cache_dir() -> Path:
    base = Path(os.environ.get("TEMP", os.environ.get("TMP", "."))) / "hirio_flea_overlay"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_output_path(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:20]
    return _overlay_cache_dir() / f"overlay_{digest}.jpg"


def _rgba(
    rgb: Tuple[int, int, int],
    opacity_percent: int,
) -> Tuple[int, int, int, int]:
    pct = max(0, min(100, int(opacity_percent)))
    alpha = int(255 * pct / 100)
    return (rgb[0], rgb[1], rgb[2], alpha)


def _load_font(
    size: int,
    font_path: Optional[str],
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(_MIN_FONT_SIZE, int(size))
    if font_path:
        indices = (1, 0) if bold else (0, 1)
        for font_index in indices:
            try:
                return ImageFont.truetype(font_path, size=size, index=font_index)
            except OSError:
                continue
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            logger.warning("truetype load failed: %s size=%s", font_path, size)
    try:
        return ImageFont.truetype("arial.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    if hasattr(draw, "textlength"):
        return float(draw.textlength(text, font=font))
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0])


def _wrap_japanese(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    max_width: int,
) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    lines: List[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if _text_width(draw, trial, font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _block_height(
    lines: List[str],
    font: ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
    line_spacing: int,
) -> int:
    if not lines:
        return 0
    total = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        total += bbox[3] - bbox[1]
        if i < len(lines) - 1:
            total += line_spacing
    return total


def _fit_font_and_lines(
    text: str,
    max_width: int,
    max_height: int,
    font_path: Optional[str],
    draw: ImageDraw.ImageDraw,
    *,
    bold: bool = False,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    text = (text or "").strip()
    if not text or max_width < 8 or max_height < 8:
        return _load_font(_MIN_FONT_SIZE, font_path, bold=bold), [], 2

    hi = min(_MAX_FONT_SIZE_CAP, max(max_height, _MIN_FONT_SIZE))
    lo = _MIN_FONT_SIZE
    best_font = _load_font(lo, font_path, bold=bold)
    best_lines: List[str] = []
    best_spacing = 2

    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid, font_path, bold=bold)
        lines = _wrap_japanese(text, draw, font, max_width)
        line_spacing = max(2, int(mid * _LINE_SPACING_RATIO))
        block_h = _block_height(lines, font, draw, line_spacing)
        if block_h <= max_height:
            best_font = font
            best_lines = lines
            best_spacing = line_spacing
            lo = mid + 1
        else:
            hi = mid - 1

    if not best_lines:
        font = _load_font(_MIN_FONT_SIZE, font_path, bold=bold)
        best_lines = _wrap_japanese(text, draw, font, max_width)
        best_font = font
        best_spacing = max(2, int(_MIN_FONT_SIZE * _LINE_SPACING_RATIO))
    return best_font, best_lines, best_spacing


def _manual_font_and_lines(
    style: TextBandStyle,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    size = max(_MIN_FONT_SIZE, int(style.font_size or _MIN_FONT_SIZE))
    font_path = resolve_font_path_for_style(style)
    font = _load_font(size, font_path, bold=style.bold)
    lines = _wrap_japanese((style.text or "").strip(), draw, font, max_width)
    line_spacing = max(2, int(size * _LINE_SPACING_RATIO))
    return font, lines, line_spacing


def _resolve_bottom_edge_inset(edge_inset: int, img_height: int) -> int:
    """下帯を画像下端から離す距離（ユーザー指定と下限の大きい方）。"""
    user = max(0, int(edge_inset))
    floor_px = _BOTTOM_INSET_MIN_PX
    floor_ratio = max(floor_px, int(img_height * _BOTTOM_INSET_MIN_HEIGHT_RATIO))
    return max(user, floor_ratio)


def _line_x(align: Align, pad_x: int, img_width: int, line_w: float) -> int:
    lw = int(line_w)
    if align == "left":
        return pad_x
    if align == "right":
        return max(pad_x, img_width - pad_x - lw)
    return max(pad_x, (img_width - lw) // 2)


def _draw_band(
    base: Image.Image,
    style: TextBandStyle,
    font: ImageFont.ImageFont,
    lines: List[str],
    line_spacing: int,
    *,
    position: str,
    img_width: int,
    img_height: int,
) -> None:
    if not lines:
        return

    draw = ImageDraw.Draw(base)
    bbox0 = draw.textbbox((0, 0), lines[0], font=font)
    line_h = bbox0[3] - bbox0[1]
    block_h = _block_height(lines, font, draw, line_spacing)

    pad_x = max(4, int(img_width * _HORIZONTAL_PAD_RATIO))
    pad_y = max(4, int(block_h * _VERTICAL_PAD_RATIO))
    is_bottom = position == "bottom"
    if is_bottom:
        pad_y_top = pad_y
        pad_y_bottom = max(pad_y, int(line_h * _BOTTOM_BAND_INNER_PAD_RATIO))
    else:
        pad_y_top = pad_y_bottom = pad_y
    inner_v = pad_y_top + block_h + pad_y_bottom

    max_ratio = (
        _BAND_MAX_HEIGHT_RATIO_AUTO
        if style.auto_size
        else _BAND_MAX_HEIGHT_RATIO_MANUAL
    )
    band_cap = int(img_height * max_ratio)
    band_h = min(band_cap, inner_v) if style.auto_size else min(band_cap, inner_v)
    band_h = max(band_h, inner_v)

    if position == "top":
        y0 = max(0, int(style.edge_inset))
    else:
        inset = _resolve_bottom_edge_inset(style.edge_inset, img_height)
        y0 = max(0, img_height - band_h - inset)

    bg_rgba = _rgba(style.bg_color, style.bg_opacity_percent)
    text_rgba = (*style.text_color[:3], 255)

    overlay = Image.new("RGBA", (img_width, band_h), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(overlay)
    band_draw.rectangle((0, 0, img_width, band_h), fill=bg_rgba)

    text_y = pad_y_top + max(0, (band_h - pad_y_top - pad_y_bottom - block_h) // 2)
    for line in lines:
        line_w = _text_width(band_draw, line, font)
        text_x = _line_x(style.align, pad_x, img_width, line_w)
        band_draw.text((text_x, text_y), line, font=font, fill=text_rgba)
        text_y += line_h + line_spacing

    base.paste(overlay, (0, y0), overlay)


def _prepare_band(
    style: TextBandStyle,
    inner_w: int,
    band_max_h: int,
    measure: ImageDraw.ImageDraw,
) -> Tuple[ImageFont.ImageFont, List[str], int]:
    if not (style.text or "").strip():
        return _load_font(_MIN_FONT_SIZE, None), [], 2
    font_path = resolve_font_path_for_style(style)
    if style.auto_size:
        return _fit_font_and_lines(
            style.text,
            inner_w,
            band_max_h - 8,
            font_path,
            measure,
            bold=style.bold,
        )
    return _manual_font_and_lines(style, inner_w, measure)


def _clamp_square_size(size: int) -> int:
    return max(MIN_FLEA_SQUARE_SIZE, min(MAX_FLEA_SQUARE_SIZE, int(size)))


def fit_image_to_square_letterbox(
    img: Image.Image,
    size: int = DEFAULT_FLEA_SQUARE_SIZE,
    bg_rgb: Tuple[int, int, int] = _DEFAULT_BG_RGB,
) -> Image.Image:
    """画像全体を切り取らず、1:1キャンバスに収める（余白あり）。"""
    size = _clamp_square_size(size)
    work = img.convert("RGB")
    w, h = work.size
    if w <= 0 or h <= 0:
        return Image.new("RGB", (size, size), bg_rgb)

    scale = min(size / w, size / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = work.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), bg_rgb)
    offset_x = (size - new_w) // 2
    offset_y = (size - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def crop_image_to_square_cover(
    img: Image.Image,
    size: int = DEFAULT_FLEA_SQUARE_SIZE,
) -> Image.Image:
    """1:1を満たすよう拡大し、中央を切り抜く（余白なし・メルカリ一覧向け）。"""
    size = _clamp_square_size(size)
    work = img.convert("RGB")
    w, h = work.size
    if w <= 0 or h <= 0:
        return Image.new("RGB", (size, size), _DEFAULT_BG_RGB)

    scale = max(size / w, size / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = work.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - size) // 2)
    top = max(0, (new_h - size) // 2)
    return resized.crop((left, top, left + size, top + size))


def export_image_to_square(
    img: Image.Image,
    size: int = DEFAULT_FLEA_SQUARE_SIZE,
    *,
    mode: Union[SquareFitMode, str] = DEFAULT_SQUARE_FIT_MODE,
    bg_rgb: Tuple[int, int, int] = _DEFAULT_BG_RGB,
) -> Image.Image:
    """1:1出力。mode: letterbox=余白収め, cover=ズーム中央クロップ。"""
    if mode == "letterbox":
        return fit_image_to_square_letterbox(img, size=size, bg_rgb=bg_rgb)
    return crop_image_to_square_cover(img, size=size)


def fit_image_to_square(
    img: Image.Image,
    size: int = DEFAULT_FLEA_SQUARE_SIZE,
    bg_rgb: Tuple[int, int, int] = _DEFAULT_BG_RGB,
) -> Image.Image:
    """後方互換: レターボックス。"""
    return fit_image_to_square_letterbox(img, size=size, bg_rgb=bg_rgb)


def _load_source_rgb(source_path: str) -> Image.Image:
    with Image.open(source_path) as src:
        img = ImageOps.exif_transpose(src)
        if img.mode not in ("RGB", "RGBA"):
            return img.convert("RGB")
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        return img.convert("RGB")


def _compose_overlay_on_rgba(
    rgba: Image.Image,
    settings: ImageOverlaySettings,
) -> Image.Image:
    """RGBA画像の上下にテキスト帯を描画する。"""
    w, h = rgba.size
    dummy = Image.new("RGBA", (w, h))
    measure = ImageDraw.Draw(dummy)

    pad_x = max(4, int(w * _HORIZONTAL_PAD_RATIO))
    inner_w = w - pad_x * 2
    band_max_h = max(32, int(h * _BAND_MAX_HEIGHT_RATIO_MANUAL))

    top_s = settings.top
    if (top_s.text or "").strip():
        font, lines, spacing = _prepare_band(top_s, inner_w, band_max_h, measure)
        _draw_band(
            rgba,
            top_s,
            font,
            lines,
            spacing,
            position="top",
            img_width=w,
            img_height=h,
        )

    bottom_s = settings.bottom
    if (bottom_s.text or "").strip():
        font, lines, spacing = _prepare_band(bottom_s, inner_w, band_max_h, measure)
        _draw_band(
            rgba,
            bottom_s,
            font,
            lines,
            spacing,
            position="bottom",
            img_width=w,
            img_height=h,
        )
    return rgba


def _resolve_square_fit_mode(settings: ImageOverlaySettings) -> SquareFitMode:
    mode = settings.square_fit_mode
    if mode not in ("letterbox", "cover"):
        return DEFAULT_SQUARE_FIT_MODE
    return mode  # type: ignore[return-value]


def apply_text_overlay(
    source_path: str,
    *,
    settings: Optional[ImageOverlaySettings] = None,
    top_text: str = "",
    bottom_text: str = "",
    output_path: Optional[str] = None,
) -> str:
    """
    元画像に上下テキスト帯を合成し JPEG で保存する。元ファイルは変更しない。

    ズーム埋め(cover)時は先に1:1にしてから帯を描画し、文字が切れないようにする。
    余白収め(letterbox)時は帯付きのまま正方形に収める。
    """
    source_path = os.path.normpath(source_path)
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"画像が見つかりません: {source_path}")

    if settings is None:
        settings = default_overlay_settings(top_text, bottom_text)
    else:
        if top_text:
            settings.top.text = top_text.strip()
        if bottom_text:
            settings.bottom.text = bottom_text.strip()

    if not settings.has_any_text():
        raise ValueError("上部または下部のテキストを1つ以上指定してください。")

    cache_key = settings.cache_key(source_path)
    dest = Path(output_path) if output_path else _cache_output_path(cache_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    img = _load_source_rgb(source_path)

    if settings.export_square and _resolve_square_fit_mode(settings) == "cover":
        square_size = _clamp_square_size(settings.square_size)
        base = crop_image_to_square_cover(img, size=square_size)
        rgba = _compose_overlay_on_rgba(base.convert("RGBA"), settings)
        out_rgb = rgba.convert("RGB")
    else:
        rgba = _compose_overlay_on_rgba(img.convert("RGBA"), settings)
        out_rgb = rgba.convert("RGB")
        if settings.export_square:
            out_rgb = export_image_to_square(
                out_rgb,
                size=settings.square_size,
                mode="letterbox",
                bg_rgb=settings.square_bg_color,
            )

    out_rgb.save(str(dest), format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return str(dest.resolve())


def product_name_from_record(record: dict) -> str:
    for key in ("商品名", "product_name", "title", "name"):
        v = record.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


BOTTOM_TEXT_PRESETS: Tuple[str, ...] = (
    "（なし）",
    "新品",
    "未使用",
    "未開封",
    "美品",
    "直接入力",
)
