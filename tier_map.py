# -*- coding: utf-8 -*-
"""
COM3D2 MOD 搜索：关键词三梯级转换（铁律逻辑内置，零 LLM 消耗）

梯级顺序：片假名（主搜）→ 汉字（日文）→ 英文（兜底）。
当前梯级结果 ≤3 件或 0 件时自动下探下一梯级并合并展示。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# 噪音词（Mukuu 本身只索引 COM3D2/CM3D2，无需重复限定）
NOISE_WORDS = ("mod", "com3d2", "cm3d2")

# 三梯级映射表：用户中文 → (片假名, 日文汉字, 英文)，None 表示该梯级无对应
TIER_MAP: dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {
    # 原 skill 映射表
    "口枷": ("ギャグ", "口枷", "ball gag"),
    "口塞": ("ギャグ", "口枷", "ball gag"),
    "口球": ("ギャグ", "口枷", "ball gag"),
    "长手套": ("ロンググローブ", "長手袋", "long gloves"),
    "过膝靴": ("ロングブーツ", "長靴", "long boots"),
    "长筒靴": ("ロングブーツ", "長靴", "long boots"),
    "手套": ("グローブ", "手袋", "gloves"),
    "鼻血": (None, "鼻血", "nosebleed"),
    "流血": (None, "流血", "blood"),
    "血": (None, "血", "blood"),
    "泳装": (None, "水着", "swimsuit"),
    "水着": (None, "水着", "swimsuit"),
    "发型": (None, "髪", "hair"),
    "头发": (None, "髪", "hair"),
    "纹身": ("タトゥー", "刺青", "tattoo"),
    "拘束": (None, "拘束", "bondage"),
    "预设": ("プリセット", None, "preset"),
    "姿势": ("ポーズ", None, "pose"),
    # 扩充常用词
    "项圈": ("チョーカー", "首輪", "choker"),
    "眼罩": ("目隠し", "目隠し", "blindfold"),
    "制服": ("セーラー服", "制服", "uniform"),
    "女仆": ("メイド服", "メイド服", "maid"),
    "女仆装": ("メイド服", "メイド服", "maid"),
    "乳胶": ("ラテックス", "ラテックス", "latex"),
    "皮带": ("ベルト", "ベルト", "belt"),
    "皮衣": ("レザー", "革", "leather"),
    "靴": ("ブーツ", "靴", "boots"),
    "吊带袜": ("ガーター", "ガーター", "garter"),
    "丝袜": ("ストッキング", "ストッキング", "stockings"),
    "黑丝": ("ストッキング", "ストッキング", "stockings"),
    "兔女郎": ("バニー", "バニー", "bunny"),
    "猫耳": ("ネコミミ", "猫耳", "cat ears"),
    "猫尾": ("ネコシッポ", "猫しっぽ", "cat tail"),
    "发带": ("リボン", "リボン", "ribbon"),
    "缎带": ("リボン", "リボン", "ribbon"),
    "项环": ("チョーカー", "首輪", "collar"),
    "手铐": ("手錠", "手錠", "handcuffs"),
    "脚镣": ("足枷", "足枷", "shackles"),
    "蜡烛": ("キャンドル", "蝋燭", "candle"),
    "鞭": ("ムチ", "鞭", "whip"),
    "尾巴": ("シッポ", "しっぽ", "tail"),
    "紧身衣": ("ボンテージ", "ボンテージ", "bondage suit"),
    "紧缚": ("緊縛", "緊縛", "shibari"),
    "眼影": ("アイシャドウ", "アイシャドウ", "eyeshadow"),
    "口红": ("リップ", "口紅", "lipstick"),
    "眼镜": ("メガネ", "眼鏡", "glasses"),
    "耳环": ("ピアス", "ピアス", "earrings"),
    "婚纱": ("ウェディングドレス", "ウェディングドレス", "wedding dress"),
    "旗袍": ("チャイナドレス", "チャイナドレス", "cheongsam"),
    "和服": ("着物", "着物", "kimono"),
    "浴衣": ("浴衣", "浴衣", "yukata"),
    "校服": ("制服", "制服", "school uniform"),
    "运动服": ("ジャージ", "ジャージ", "jersey"),
    "体操服": ("体操服", "体操服", "gym uniform"),
    "裸足": ("裸足", "裸足", "barefoot"),
    "脚": ("足", "足", "feet"),
    "袜子": ("ソックス", "靴下", "socks"),
    "内裤": ("パンツ", "下着", "panties"),
    "内衣": ("下着", "下着", "lingerie"),
    "胸罩": ("ブラ", "ブラジャー", "bra"),
    "浴巾": ("バスタオル", "バスタオル", "towel"),
    "围裙": ("エプロン", "エプロン", "apron"),
    "护士": ("ナース", "ナース", "nurse"),
    "警察": ("ポリス", "警察", "police"),
    "军装": ("軍服", "軍服", "military"),
    "哥特": ("ゴスロリ", "ゴスロリ", "gothic lolita"),
    "洛丽塔": ("ロリータ", "ロリータ", "lolita"),
}

_JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")


def strip_noise(keyword: str) -> str:
    """剥离噪音词（大小写不敏感）。"""
    low = keyword.lower()
    for w in NOISE_WORDS:
        low = low.replace(w, "")
    return re.sub(r"\s+", " ", low).strip()


def _lookup(keyword: str) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """先精确匹配，再包含匹配（取最长命中）。"""
    if keyword in TIER_MAP:
        return TIER_MAP[keyword]
    hit = None
    for k, v in TIER_MAP.items():
        if k in keyword and (hit is None or len(k) > len(hit[0])):
            hit = (k, v)
    return hit[1] if hit else None


def build_queries(keyword: str) -> List[Tuple[str, str]]:
    """
    返回 [(查询词, 梯级名), ...]，按 片假名→汉字→英文 顺序。
    表内命中 → 三梯级；表外 → 原样返回（原文）。
    """
    kw = strip_noise(keyword)
    if not kw:
        return []
    m = _lookup(keyword)
    if not m:
        return [(kw, "原文")]
    tier_names = ("片假名", "汉字", "英文")
    out = []
    for val, name in zip(m, tier_names):
        if val:
            out.append((val, name))
    return out or [(kw, "原文")]
