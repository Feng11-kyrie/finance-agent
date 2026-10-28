"""
Google Sheets 数据库 - 用户持仓存储
支持：Streamlit 网站写入 / GitHub Actions 读取报告
"""

import json
import os

SHEET_HEADERS = [
    "name", "code", "item_name", "type",
    "alert_change_pct", "alert_nav_below", "sendkey", "cc_target",
]


def _col_letter(index: int) -> str:
    """1 → A, 8 → H（表头最多 8 列）。"""
    return chr(64 + index)


def _secret(key: str) -> str:
    """优先环境变量（本地 cron / GitHub Actions），其次 Streamlit secrets。"""
    value = os.environ.get(key, "")
    if value:
        return value
    try:
        import streamlit as st
        value = st.secrets.get(key, "")
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    except Exception:
        return ""


def _safe_int(value, default: int = 0) -> int:
    """Sheets 单元格可能是空串、'3%'、'3.0' 等，避免 int() 直接抛异常。"""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _clean_code(value) -> str:
    """218 / 218.0 / '000218' → 000218，兼容 Sheets 把代码当数字。"""
    text = str(value).strip().lstrip("'")
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _get_sheet():
    """懒加载 Google Sheets 连接"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = _secret("GCP_SERVICE_ACCOUNT")
    if not creds_json:
        raise RuntimeError("GCP_SERVICE_ACCOUNT 环境变量未配置")

    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    sheet_id = _secret("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID 环境变量未配置")
    return client.open_by_key(sheet_id).sheet1


def ensure_headers(sheet=None) -> None:
    """确保表头包含 sendkey / cc_target。

    已有 6 列表格会自动在 G/H 列补表头，不影响旧数据。
    """
    sheet = sheet or _get_sheet()
    values = sheet.get_all_values()
    if not values or not values[0]:
        sheet.update("A1:H1", [SHEET_HEADERS])
        return

    header = [str(h).strip() for h in values[0]]
    missing = [h for h in SHEET_HEADERS if h not in header]
    if not missing:
        return

    start = len(header) + 1
    end = start + len(missing) - 1
    sheet.update(
        f"{_col_letter(start)}1:{_col_letter(end)}1",
        [missing],
    )


# ═══════════════════════════════════════════════
# 读取
# ═══════════════════════════════════════════════

def load_all_users() -> list[dict]:
    """从 Google Sheets 读取所有用户及其持仓"""
    try:
        sheet = _get_sheet()
        records = sheet.get_all_records()
    except Exception as e:
        print(f"⚠️ Google Sheets 读取失败，回退到本地文件: {e}")
        return _load_from_local_files()

    if not records:
        print("⚠️ Google Sheets 为空")
        return []

    users = {}
    for row in records:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        if name not in users:
            users[name] = {
                "name": name,
                "sendkey": "",
                "cc_target": "",
                "watchlist": {"stocks": [], "funds": []},
            }

        # 可选的 sendkey / cc_target 列：不配则用全局 SendKey / Server酱
        sendkey = str(row.get("sendkey", "")).strip()
        if sendkey:
            users[name]["sendkey"] = sendkey
        cc_target = str(row.get("cc_target", "")).strip()
        if cc_target:
            users[name]["cc_target"] = cc_target

        code = _clean_code(row.get("code", ""))
        if not code:
            continue
        item_name = str(row.get("item_name", "")).strip()
        item_type = str(row.get("type", "fund")).strip().lower()


        item = {
            "code": code,
            "name": item_name,
            "alert_change_pct": _safe_int(row.get("alert_change_pct"), 3),
            "alert_nav_below": _safe_int(row.get("alert_nav_below"), 0),
        }
        if item_type == "stock":
            users[name]["watchlist"]["stocks"].append(item)
        else:
            users[name]["watchlist"]["funds"].append(item)

    # 重复提交/导入会产生重复行：同类型同代码保留最后一条（最新一次写入）
    for user in users.values():
        for kind in ("stocks", "funds"):
            unique = {}
            for item in user["watchlist"][kind]:
                unique[item["code"]] = item
            user["watchlist"][kind] = list(unique.values())

    result = list(users.values())
    print(f"✅ 从 Google Sheets 加载了 {len(result)} 个用户")
    for u in result:
        total = len(u["watchlist"]["stocks"]) + len(u["watchlist"]["funds"])
        print(f"   {u['name']}: {total} 个持仓")
    return result


def _load_from_local_files() -> list[dict]:
    """本地文件回退（开发/过渡用）"""
    users_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users")
    users = []
    if not os.path.isdir(users_dir):
        return users
    for fname in sorted(os.listdir(users_dir)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(users_dir, fname), encoding="utf-8") as f:
                    user = json.load(f)
                    user["_file"] = fname
                    users.append(user)
            except Exception:
                pass
    return users


# ═══════════════════════════════════════════════
# 写入（Streamlit 网站用）
# ═══════════════════════════════════════════════

def add_user_holdings(name: str, funds: list[dict], stocks: list[dict],
                      sendkey: str = "", cc_target: str = "") -> bool:
    """添加用户持仓到 Google Sheets（自动补齐 sendkey/cc_target 表头）"""
    sheet = _get_sheet()
    ensure_headers(sheet)
    rows = []
    for f in funds:
        code = _clean_code(f.get("code", ""))
        if not code:
            continue
        # 单引号前缀防止 Google Sheets 把代码当数字（吞掉前导零）
        rows.append([
            name,
            f"'{code}",
            str(f.get("name", "")),
            "fund",
            _safe_int(f.get("alert_change_pct"), 3),
            _safe_int(f.get("alert_nav_below"), 0),
            sendkey,
            cc_target,
        ])
    for s in stocks:
        code = _clean_code(s.get("code", ""))
        if not code:
            continue
        rows.append([
            name,
            f"'{code}",
            str(s.get("name", "")),
            "stock",
            _safe_int(s.get("alert_change_pct"), 5),
            _safe_int(s.get("alert_below"), 0),
            sendkey,
            cc_target,
        ])
    if rows:
        sheet.append_rows(rows)
        print(f"✅ 已添加 {len(rows)} 条持仓")
    return True


def init_sheet_headers():
    """初始化/补齐 Sheet 表头"""
    ensure_headers()
    print("✅ 已初始化表头")
