"""
本地存储：登录凭证 + 历史记录。

凭证存在项目目录下的 data/auth.json，不往任何服务器上传。
明文存 token 是有意为之——这样你自己能打开文件看到里面存了什么，
想注销直接删掉这个文件就行，不用猜它藏在哪。

（如果你想把凭证放到别处，设环境变量 COUPON_HUNTER_DATA 指向一个目录即可。）
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("COUPON_HUNTER_DATA")
    base = Path(override) if override else PROJECT_ROOT / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Path, obj, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    if private:
        # 尽量收紧权限，别让同机器上的其他用户读到登录凭证。
        # Windows 上 os.chmod 只能切只读位（ACL 才是真正的权限控制），
        # 所以这里主要对 macOS / Linux 有效；Windows 请依赖你的用户目录权限。
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────
# 登录凭证
# ──────────────────────────────────────────────────────────

def auth_path() -> Path:
    return data_dir() / "auth.json"


def load_auth() -> dict:
    return _read_json(auth_path(), {})


def save_auth(data: dict) -> None:
    # private=True：这个文件里有你的登录 token，权限尽量收紧
    _write_json(auth_path(), data, private=True)


def clear_auth() -> None:
    p = auth_path()
    if p.exists():
        p.unlink()


def mask_phone(phone: str) -> str:
    """13812345678 -> 138****5678"""
    if len(phone) == 11:
        return phone[:3] + "****" + phone[-4:]
    return phone


# ──────────────────────────────────────────────────────────
# 领取历史（用来判断「今天是不是已经领过了」）
# ──────────────────────────────────────────────────────────

def history_path() -> Path:
    return data_dir() / "history.json"


def load_history() -> list[dict]:
    return _read_json(history_path(), [])


def append_history(coupons: list, source: str, action: str = "search") -> None:
    """记一笔历史。

    action 必须是 "search"（只是搜到了）或 "claim"（真的领到手了）。
    这两件事必须分开记，否则「今天已领过」会被搜索记录误判成 True，
    导致明明还能领却提示你已经领过了。这个 bug 之前真实存在过。
    """
    hist = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for c in coupons:
        hist.append(
            {
                "time": now,
                "date": today,
                "action": action,
                "source": source,
                "platform": c.platform,
                "title": c.title,
                "code": c.code,
                "discount": c.discount_text(),
            }
        )
    # 只保留最近 500 条，避免文件无限膨胀
    _write_json(history_path(), hist[-500:])


def claimed_dates(platform: str | None = None) -> set[str]:
    """返回「真正领取过」的日期集合。

    只有 action == "claim" 的记录才算数。历史文件里没有 action 字段的老记录
    一律当成 search 处理——宁可漏报「已领过」，也不能误报导致你少领一张券。
    """
    dates = set()
    for row in load_history():
        if row.get("action") != "claim":
            continue
        if platform and row.get("platform") != platform:
            continue
        if row.get("date"):
            dates.add(row["date"])
    return dates


def is_claimed_today(platform: str) -> bool:
    return datetime.now().strftime("%Y-%m-%d") in claimed_dates(platform)
