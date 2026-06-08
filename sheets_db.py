"""
Google Sheets 数据库 - 用户持仓存储
支持：Streamlit 网站写入 / GitHub Actions 读取报告
"""

import json
import os


def _get_sheet():
    """懒加载 Google Sheets 连接"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT", "")
    if not creds_json:
        raise RuntimeError("GCP_SERVICE_ACCOUNT 环境变量未配置")

    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID 环境变量未配置")
    return client.open_by_key(sheet_id).sheet1


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
            users[name] = {"name": name, "watchlist": {"stocks": [], "funds": []}}

        code = str(row.get("code", "")).strip()
        # Google Sheets 可能把代码当数字吞掉前导零，补齐到6位
        code = code.zfill(6)
        item_name = str(row.get("item_name", "")).strip()
        item_type = str(row.get("type", "fund")).strip()

        item = {
            "code": code,
            "name": item_name,
            "alert_change_pct": int(row.get("alert_change_pct", 3)),
            "alert_nav_below": int(row.get("alert_nav_below", 0)),
        }
        if item_type == "stock":
            users[name]["watchlist"]["stocks"].append(item)
        else:
            users[name]["watchlist"]["funds"].append(item)

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
                with open(os.path.join(users_dir, fname)) as f:
                    user = json.load(f)
                    user["_file"] = fname
                    users.append(user)
            except Exception:
                pass
    return users


# ═══════════════════════════════════════════════
# 写入（Streamlit 网站用）
# ═══════════════════════════════════════════════

def add_user_holdings(name: str, funds: list[dict], stocks: list[dict]) -> bool:
    """添加用户持仓到 Google Sheets"""
    sheet = _get_sheet()
    rows = []
    for f in funds:
        code = str(f.get("code", ""))
        # 单引号前缀防止 Google Sheets 把代码当数字（吞掉前导零）
        rows.append([
            name,
            f"'{code}",
            str(f.get("name", "")),
            "fund",
            int(f.get("alert_change_pct", 3)),
            int(f.get("alert_nav_below", 0)),
        ])
    for s in stocks:
        code = str(s.get("code", ""))
        rows.append([
            name,
            f"'{code}",
            str(s.get("name", "")),
            "stock",
            int(s.get("alert_change_pct", 5)),
            int(s.get("alert_below", 0)),
        ])
    if rows:
        sheet.append_rows(rows)
        print(f"✅ 已添加 {len(rows)} 条持仓")
    return True


def init_sheet_headers():
    """初始化 Sheet 表头（仅首次）"""
    sheet = _get_sheet()
    existing = sheet.get_all_values()
    if not existing or not existing[0]:
        sheet.update("A1:F1", [["name", "code", "item_name", "type",
                                "alert_change_pct", "alert_nav_below"]])
        print("✅ 已初始化表头")
