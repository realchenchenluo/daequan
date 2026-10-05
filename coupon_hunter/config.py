"""读取 config.json。文件不存在时用内置的默认配置，保证开箱即用。"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULT_CONFIG = {
    "sources": [
        {
            "id": "free_aggregator",
            "type": "aggregator",
            "enabled": True,
            "label": "免费聚合口令源",
            "endpoint": "https://agskills.moontai.top/coupon/takeout",
        },
        {
            "id": "meituan_official",
            "type": "meituan_official",
            "enabled": True,
            "label": "美团官方直发券",
            # 刻意留空：内置别人的推广编号 = 你领券的佣金归别人。
            # 要用请去 https://union.meituan.com 注册后填自己的。
            "ai_scene": "",
            "auto_claim": False,
        },
    ]
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg.get("sources"), list):
                return cfg
        except Exception as e:
            print(f"  ⚠️ config.json 读取失败，改用默认配置（原因：{e}）")
    return DEFAULT_CONFIG


def save_default_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
