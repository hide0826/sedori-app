#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa 3-6-9 解析・Gemini 解釈（Mixin）。"""

from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
import statistics
import json

from PySide6.QtCore import QSettings


class Keepa369AnalysisMixin:
    """時系列・sales drops・369 解析・Gemini。"""

    # ---------------------------
    # 3-6-9 ロジック向け解析
    # ---------------------------
    _KEEPA_EPOCH = datetime(2011, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def _keepa_minutes_to_datetime(cls, keepa_minutes: float) -> datetime:
        return cls._KEEPA_EPOCH + timedelta(minutes=float(keepa_minutes))

    @staticmethod
    def _to_float_or_none(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            v = float(value)
            return v
        except (TypeError, ValueError):
            return None

    def _extract_time_series(
        self,
        raw_product: Dict[str, Any],
        key_candidates: List[str],
    ) -> List[Tuple[datetime, float]]:
        """
        Keepa raw product の data/csv から時系列を取り出す。
        - keepa ライブラリ経由の data[key]（値のみ配列）にも対応
        - 生 csv の [minute, value, minute, value, ...] にも対応
        """
        # 1) data キーから取得
        data = raw_product.get("data") or {}
        for key in key_candidates:
            series = data.get(key)
            if series is None:
                continue
            try:
                seq = list(series)
            except TypeError:
                continue
            if not seq:
                continue
            # keepa.convert_history が使える場合はそれを最優先
            try:
                import keepa  # type: ignore
                if hasattr(keepa, "convert_history"):
                    times, values = keepa.convert_history(seq)  # type: ignore[attr-defined]
                    out: List[Tuple[datetime, float]] = []
                    if times is not None and values is not None:
                        for t, v in zip(times, values):
                            fv = self._to_float_or_none(v)
                            if fv is None or fv <= 0:
                                continue
                            if isinstance(t, datetime):
                                out.append((t if t.tzinfo else t.replace(tzinfo=timezone.utc), fv))
                            else:
                                tv = self._to_float_or_none(t)
                                if tv is not None:
                                    out.append((self._keepa_minutes_to_datetime(tv), fv))
                    if out:
                        return out
            except Exception:
                pass

            # フォールバック: [m, v, m, v, ...]
            if len(seq) >= 2:
                out = []
                for i in range(0, len(seq) - 1, 2):
                    m = self._to_float_or_none(seq[i])
                    v = self._to_float_or_none(seq[i + 1])
                    if m is None or v is None or v <= 0:
                        continue
                    out.append((self._keepa_minutes_to_datetime(m), v))
                if out:
                    return out

        # 2) 生 csv フィールドから取得（エクスポートJSON互換）
        csv_field = raw_product.get("csv") or {}
        for key in key_candidates:
            series = csv_field.get(key)
            if series is None:
                continue
            try:
                seq = list(series)
            except TypeError:
                continue
            out = []
            for i in range(0, len(seq) - 1, 2):
                m = self._to_float_or_none(seq[i])
                v = self._to_float_or_none(seq[i + 1])
                if m is None or v is None or v <= 0:
                    continue
                out.append((self._keepa_minutes_to_datetime(m), v))
            if out:
                return out
        return []

    @staticmethod
    def _slice_series(
        series: List[Tuple[datetime, float]],
        *,
        window_days: int,
    ) -> List[Tuple[datetime, float]]:
        if not series:
            return []
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=window_days)
        return [(t, v) for t, v in series if t >= since]

    @staticmethod
    def _count_sales_drops(rank_series: List[Tuple[datetime, float]]) -> int:
        """
        SALESランクのドロップ数（順位が良化=数値が減少）を近似カウント。
        小さなノイズを避けるため、直前比3%以上改善をドロップとみなす。
        """
        if len(rank_series) < 2:
            return 0
        count = 0
        prev = rank_series[0][1]
        for _, cur in rank_series[1:]:
            if prev > 0 and cur > 0:
                improved_ratio = (prev - cur) / prev
                if improved_ratio >= 0.03:
                    count += 1
            prev = cur
        return count

    @staticmethod
    def _infer_sales_from_offer_count(offer_count_series: List[Tuple[datetime, float]]) -> int:
        """
        ランキング欠落時の代替判定:
        出品者数が減少した変化を「実売推測」としてカウント。
        """
        if len(offer_count_series) < 2:
            return 0
        inferred = 0
        prev = int(round(offer_count_series[0][1]))
        for _, cur_raw in offer_count_series[1:]:
            cur = int(round(cur_raw))
            if cur < prev:
                inferred += (prev - cur)
            prev = cur
        return max(inferred, 0)

    @staticmethod
    def _series_avg_and_range(series: List[Tuple[datetime, float]]) -> Tuple[Optional[float], Optional[float]]:
        if not series:
            return None, None
        vals = [v for _, v in series if v > 0]
        if not vals:
            return None, None
        return float(statistics.mean(vals)), float(max(vals) - min(vals))

    def analyze_keepa_for_369(
        self,
        raw_product: Dict[str, Any],
        *,
        window_days: int = 90,
    ) -> Dict[str, Any]:
        """
        Keepaデータから3-6-9ロジック用の判断材料を抽出する（非AI）。
        """
        w = max(1, min(int(window_days), 365))

        sales_series = self._slice_series(
            self._extract_time_series(raw_product, ["SALES", "sales", "sales_rank"]),
            window_days=w,
        )
        used_price_series = self._slice_series(
            self._extract_time_series(raw_product, ["USED", "USED_NEWBIE", "used_price"]),
            window_days=w,
        )
        used_offer_count_series = self._slice_series(
            self._extract_time_series(raw_product, ["COUNT_USED", "USED_OFFER_COUNT", "count_used"]),
            window_days=w,
        )

        c_vg = self._slice_series(
            self._extract_time_series(raw_product, ["USED_VERY_GOOD_SHIPPING", "COUNT_USED_VERY_GOOD"]),
            window_days=w,
        )
        c_g = self._slice_series(
            self._extract_time_series(raw_product, ["USED_GOOD_SHIPPING", "COUNT_USED_GOOD"]),
            window_days=w,
        )
        c_a = self._slice_series(
            self._extract_time_series(raw_product, ["USED_ACCEPTABLE_SHIPPING", "COUNT_USED_ACCEPTABLE"]),
            window_days=w,
        )

        sales_drop_count = self._count_sales_drops(sales_series)
        inferred_sales_count = self._infer_sales_from_offer_count(used_offer_count_series)
        total_effective_drop_count = sales_drop_count + inferred_sales_count

        used_avg, used_range = self._series_avg_and_range(used_price_series)
        offer_delta = None
        if len(used_offer_count_series) >= 2:
            offer_delta = int(round(used_offer_count_series[-1][1] - used_offer_count_series[0][1]))

        def _summary(series: List[Tuple[datetime, float]]) -> Dict[str, Optional[float]]:
            avg, rg = self._series_avg_and_range(series)
            return {
                "avg": avg,
                "range": rg,
                "latest": series[-1][1] if series else None,
            }

        result = {
            "window_days": w,
            "sales_drop_count": sales_drop_count,
            "inferred_sales_count": inferred_sales_count,
            "total_effective_drop_count": total_effective_drop_count,
            "used_price_avg": used_avg,
            "used_price_range": used_range,
            "used_offer_count_delta": offer_delta,
            "condition_price_summary": {
                "very_good": _summary(c_vg),
                "good": _summary(c_g),
                "acceptable": _summary(c_a),
            },
        }
        return result

    def interpret_369_with_gemini(
        self,
        analysis: Dict[str, Any],
        *,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        抽出済み分析データをGeminiに渡して、運用モードと補正値を返す。
        補正値は -5.0〜+5.0% にクリップする。
        """
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        model_name = resolve_gemini_flash_model(model_name)
        if api_key is None:
            settings = QSettings("HIRIO", "DesktopApp")
            api_key = (settings.value("ocr/gemini_api_key", "") or "").strip() or None
        if not api_key:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": "Gemini APIキー未設定のため、補正値は0%。",
            }
        try:
            import google.generativeai as genai  # type: ignore
        except Exception:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": "google-generativeai未導入のため、補正値は0%。",
            }

        prompt = (
            "あなたは中古せどり価格戦略アシスタントです。"
            "以下の3-6-9分析データを見て、運用モードと補正値を返してください。"
            "出力はJSONのみ。\n\n"
            "判定基準:\n"
            "- 月間ドロップ10回以上: 高回転（利益追求寄り、+2~+3%も可）\n"
            "- 月間ドロップ2回以下: 滞留リスク（回転重視、早め値下げ）\n"
            "- ランキング欠落時は inferred_sales_count を実売推測として含める\n"
            "- 出品者数急増なら回避行動（補正をマイナス）\n\n"
            "出力スキーマ:\n"
            "{\n"
            '  "mode": "利益追求|バランス|回転重視",\n'
            '  "ai_adjustment_percent": number,  // -5.0 〜 +5.0\n'
            '  "reasoning": "日本語で根拠"\n'
            "}\n\n"
            f"分析データ:\n{json.dumps(analysis, ensure_ascii=False)}"
        )
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 512,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content(prompt)
            text = getattr(response, "text", "") or ""
            if not text and getattr(response, "candidates", None):
                parts = response.candidates[0].content.parts  # type: ignore[attr-defined]
                if parts:
                    text = parts[0].text
            parsed: Dict[str, Any] = json.loads(text)
        except Exception as e:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": f"Gemini判定失敗のため補正値は0%。詳細: {e}",
            }

        mode = str(parsed.get("mode", "バランス"))
        if mode not in ("利益追求", "バランス", "回転重視"):
            mode = "バランス"
        adj = self._to_float_or_none(parsed.get("ai_adjustment_percent"))
        if adj is None:
            adj = 0.0
        adj = max(-5.0, min(5.0, float(adj)))
        reasoning = str(parsed.get("reasoning", "") or "").strip() or "根拠なし"
        return {
            "mode": mode,
            "ai_adjustment_percent": adj,
            "reasoning": reasoning,
        }

    def run_369_analysis_with_ai(
        self,
        raw_product: Dict[str, Any],
        *,
        window_days: int = 90,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        3-6-9ロジックの最終出力を返す。
        出力:
        - 実売推測込みドロップ数
        - 推奨運用モード
        - AI補正値（±5%）
        - 根拠
        """
        analysis = self.analyze_keepa_for_369(raw_product, window_days=window_days)
        ai_result = self.interpret_369_with_gemini(
            analysis,
            api_key=api_key,
            model_name=model_name,
        )
        return {
            "drop_count": int(analysis.get("total_effective_drop_count", 0) or 0),
            "sales_drop_count": int(analysis.get("sales_drop_count", 0) or 0),
            "inferred_sales_count": int(analysis.get("inferred_sales_count", 0) or 0),
            "mode": ai_result.get("mode", "バランス"),
            "ai_adjustment_percent": float(ai_result.get("ai_adjustment_percent", 0.0) or 0.0),
            "reasoning": str(ai_result.get("reasoning", "") or ""),
            "analysis": analysis,
        }

    def build_price_sell_probability_estimates(
        self,
        analysis: Dict[str, Any],
        *,
        lower_price: Optional[float],
        planned_price: Optional[float],
        step_count: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        解析結果から「価格ごとの売れる確率（推定）」を簡易算出する。
        厳密予測ではなく、比較のためのヒューリスティック指標。
        """
        lp = self._to_float_or_none(lower_price)
        pp = self._to_float_or_none(planned_price)
        if lp is None and pp is None:
            return []
        if lp is None:
            lp = pp
        if pp is None:
            pp = lp
        if lp is None or pp is None:
            return []
        low = min(lp, pp)
        high = max(lp, pp)
        if high <= 0:
            return []
        if abs(high - low) < 1:
            prices = [int(round(low))]
        else:
            n = max(3, min(int(step_count), 15))
            step = (high - low) / (n - 1)
            prices = [int(round(low + step * i)) for i in range(n)]

        drop_count = float(analysis.get("total_effective_drop_count", 0) or 0)
        offer_delta = analysis.get("used_offer_count_delta")
        offer_delta_f = float(offer_delta) if offer_delta is not None else 0.0
        used_avg = self._to_float_or_none(analysis.get("used_price_avg"))
        used_range = self._to_float_or_none(analysis.get("used_price_range")) or 0.0

        # ベース需要: ドロップ数が多いほど上がる（0.05〜0.95）
        base_demand = max(0.05, min(0.95, 0.15 + (drop_count / 20.0)))
        # 競合圧: 出品者増で悪化、減で改善
        competition_pressure = max(-0.25, min(0.25, offer_delta_f / 40.0))

        out: List[Dict[str, Any]] = []
        band_width = max(200.0, used_range * 0.6)
        for p in prices:
            # 価格が安いほど売れやすい（low→+0.18, high→-0.18）
            rel = 0.0
            if high > low:
                rel = (p - low) / (high - low)  # 0..1
            price_factor = (0.18 - rel * 0.36)

            market_fit = 0.0
            if used_avg is not None and used_avg > 0:
                distance = abs(p - used_avg)
                market_fit = max(-0.2, 0.14 - (distance / band_width) * 0.14)

            prob = base_demand + price_factor - competition_pressure + market_fit
            prob = max(0.01, min(0.99, prob))
            out.append(
                {
                    "price": int(p),
                    "sell_probability": round(prob, 4),
                    "sell_probability_percent": round(prob * 100.0, 1),
                }
            )
        return out
