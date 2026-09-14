"""
纏論交易理由生成器
根據市場數據和纏論分析，產生詳細的交易理由說明
"""
from typing import Dict, Optional


def generate_buy_reason(rsi: float, czsc: Dict, price_percentile: float,
                        neural_gate: int, neural_diff: float,
                        practical_skill: str = "", confidence: float = 0,
                        has_position: bool = False) -> str:
    """生成詳細買入理由"""
    parts = []

    # RSI 說明
    if rsi is not None:
        if rsi <= 20:
            parts.append(f"RSI{rsi:.0f}嚴重超賣")
        elif rsi <= 30:
            parts.append(f"RSI{rsi:.0f}超賣區")
        elif rsi <= 40:
            parts.append(f"RSI{rsi:.0f}偏弱")
        else:
            parts.append(f"RSI{rsi:.0f}")

    # 價格位置
    if price_percentile <= 10:
        parts.append("價格處於近期最低10%")
    elif price_percentile <= 25:
        parts.append("價格位於低檔25%")
    elif price_percentile <= 40:
        parts.append("價格回檔至中低點")

    # 纏論結構
    czsc_dir = czsc.get("last_bi_direction", "unknown")
    czsc_bull = czsc.get("bullish_score", 50)
    czsc_bear = czsc.get("bearish_score", 50)
    in_zs = czsc.get("in_zs", False)
    zs_high = czsc.get("zs_high", 0)
    zs_low = czsc.get("zs_low", 0)

    if in_zs and zs_low and zs_high:
        parts.append(f"中樞震盪({zs_low:.1f}-{zs_high:.1f})")
        if price_percentile < 30:
            parts.append("觸及中樞下沿支撐")

    if czsc_dir == "up":
        parts.append("最後一筆向上")
    elif czsc_dir == "down":
        if not has_position:
            parts.append("下跌筆末端")
        else:
            parts.append("最後一筆向下")

    if czsc_bull > czsc_bear + 15:
        parts.append(f"多頭壓倒(多空{czsc_bull:.0f}/{czsc_bear:.0f})")
    elif czsc_bull > czsc_bear:
        parts.append(f"多頭略優(多空{czsc_bull:.0f}/{czsc_bear:.0f})")

    # 實戰技能
    if practical_skill:
        skill_desc = {
            "bottom_fractal": "底分型確認買入",
            "pullback_buy": "上漲趨勢回踩中樞上沿入場",
            "pivot_breakout": "中樞向上突破跟進",
            "trend_follow": "順勢做多",
            "divergence_reversal": "底背離反轉買入",
            "top_fractal": "",
        }.get(practical_skill, practical_skill)
        if skill_desc:
            parts.append(skill_desc)
        if confidence > 0:
            parts.append(f"實戰信心{confidence:.0f}%")

    # 神經數據
    if neural_gate >= 3:
        parts.append(f"神經閘門放電{neural_gate}")
    if abs(neural_diff) >= 3:
        parts.append(f"左右腦差{neural_diff:.1f}Hz")

    return " · ".join(parts)


def generate_sell_reason(rsi: float, czsc: Dict, price_percentile: float,
                         neural_gate: int, neural_diff: float,
                         practical_skill: str = "", confidence: float = 0,
                         has_position: bool = True) -> str:
    """生成詳細賣出理由"""
    parts = []

    # RSI 說明
    if rsi is not None:
        if rsi >= 80:
            parts.append(f"RSI{rsi:.0f}嚴重超買")
        elif rsi >= 70:
            parts.append(f"RSI{rsi:.0f}超買區")
        elif rsi >= 60:
            parts.append(f"RSI{rsi:.0f}偏強")
        else:
            parts.append(f"RSI{rsi:.0f}")

    # 價格位置
    if price_percentile >= 90:
        parts.append("價格處於近期最高10%")
    elif price_percentile >= 75:
        parts.append("價格位於高檔75%")
    elif price_percentile >= 60:
        parts.append("價格反彈至中高點")

    # 纏論結構
    czsc_dir = czsc.get("last_bi_direction", "unknown")
    czsc_bull = czsc.get("bullish_score", 50)
    czsc_bear = czsc.get("bearish_score", 50)
    in_zs = czsc.get("in_zs", False)
    zs_high = czsc.get("zs_high", 0)
    zs_low = czsc.get("zs_low", 0)

    if in_zs and zs_low and zs_high:
        parts.append(f"中樞震盪({zs_low:.1f}-{zs_high:.1f})")
        if price_percentile > 70:
            parts.append("觸及中樞上沿壓力")

    if czsc_dir == "down":
        parts.append("最後一筆向下")
    elif czsc_dir == "up":
        parts.append("上漲筆末端")

    if czsc_bear > czsc_bull + 15:
        parts.append(f"空頭壓倒(多空{czsc_bull:.0f}/{czsc_bear:.0f})")
    elif czsc_bear > czsc_bull:
        parts.append(f"空頭略優(多空{czsc_bull:.0f}/{czsc_bear:.0f})")

    # 實戰技能
    if practical_skill:
        skill_desc = {
            "top_fractal": "頂分型確認賣出",
            "divergence_reversal": "頂背離反轉賣出",
            "pivot_breakout": "中樞向下突破離場",
            "trend_follow": "趨勢轉弱離場",
            "pullback_buy": "",
            "bottom_fractal": "",
        }.get(practical_skill, practical_skill)
        if skill_desc:
            parts.append(skill_desc)
        if confidence > 0:
            parts.append(f"實戰信心{confidence:.0f}%")

    # 神經數據
    if neural_gate >= 3:
        parts.append(f"神經閘門放電{neural_gate}")
    if abs(neural_diff) >= 3:
        parts.append(f"左右腦差{neural_diff:.1f}Hz")

    return " · ".join(parts)
