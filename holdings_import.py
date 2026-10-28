"""持仓文件导入 - CSV / Excel 解析、列名识别与校验。

不依赖 Streamlit，可单独测试；Web 端只负责上传、预览和确认。
支持券商、天天基金等导出的常见列名，也支持本项目提供的模板。
"""
from __future__ import annotations

import io
import math
import re

import pandas as pd

# 列名别名（会先做归一化：去空格/标点、转小写）
ALIASES = {
    "type": ["类型", "品种", "类别", "资产类型", "业务类型", "type"],
    "code": ["代码", "基金代码", "股票代码", "证券代码", "基金编码", "code"],
    "name": ["名称", "基金名称", "股票名称", "证券名称", "产品名称", "简称", "name"],
    "price": [
        "买入价", "买入净值", "成本价", "成本单价", "持仓成本", "成本",
        "price", "cost",
    ],
    "shares": [
        "数量", "份额", "持有份额", "持仓数量", "持有数量", "股数",
        "shares", "quantity",
    ],
    "amount": [
        "金额", "买入金额", "投入金额", "成本金额", "持仓金额",
        "amount",
    ],
}

CSV_TEMPLATE = (
    "类型,代码,名称,买入价,数量,金额\n"
    "基金,000218,国泰黄金ETF联接A,3.1049,,10000\n"
    "股票,600519,贵州茅台,1500.00,100,\n"
)

FUND_HINTS = ("基金", "etf", "lof", "qdii", "混合", "债券", "指数", "联接", "货币")
STOCK_HINTS = ("股票", "a股", "stock")


def _norm(value) -> str:
    return re.sub(r"[\s_\-—（）()【】\[\]/]+", "", str(value)).lower()


def _num(value):
    """把 '1,234.50' / '¥3.10' / 1234.5 统一转成 float，空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    text = text.replace("元", "").replace("份", "").replace("股", "")
    if not text or text.lower() in ("nan", "none", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_code(value) -> str:
    """把代码统一成 6 位字符串：218 / 218.0 / '000218' → 000218。"""
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        text = str(int(value)) if value.is_integer() else str(value)
    else:
        text = str(value).strip().lstrip("'")
        if text.endswith(".0"):
            text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    return digits.zfill(6)


def detect_columns(columns) -> dict:
    """按列名别名识别字段；先精确匹配，再子串匹配。"""
    normalized = [(str(col), _norm(col)) for col in columns]
    mapping = {}
    used = set()

    for field, aliases in ALIASES.items():
        for alias in aliases:
            target = _norm(alias)
            for col, norm_col in normalized:
                if col in used:
                    continue
                if norm_col == target:
                    mapping[field] = col
                    used.add(col)
                    break
            if field in mapping:
                break

    for field, aliases in ALIASES.items():
        if field in mapping:
            continue
        for alias in aliases:
            target = _norm(alias)
            for col, norm_col in normalized:
                if col in used:
                    continue
                if target in norm_col:
                    mapping[field] = col
                    used.add(col)
                    break
            if field in mapping:
                break

    return mapping


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """读取 CSV / XLSX 为 DataFrame。CSV 兼容 UTF-8 BOM 与 GBK。"""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))

    last_error = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return pd.read_csv(
                io.BytesIO(data), encoding=encoding, sep=None, engine="python"
            )
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise ValueError(f"无法识别 CSV 编码，请另存为 UTF-8 后重试（{last_error}）")


def _infer_type(raw_type, name: str, mapping: dict, default_type: str) -> str:
    text = _norm(raw_type)
    name_text = _norm(name)

    if any(hint in text for hint in STOCK_HINTS):
        return "stock"
    if any(hint in text for hint in FUND_HINTS):
        return "fund"
    if default_type in ("stock", "fund"):
        return default_type
    if any(hint in name_text for hint in FUND_HINTS):
        return "fund"

    shares_col = _norm(mapping.get("shares", ""))
    if "份额" in shares_col:
        return "fund"
    if "股" in shares_col:
        return "stock"
    if "amount" in mapping and "shares" not in mapping:
        return "fund"
    if "shares" in mapping and "amount" not in mapping:
        return "stock"
    return "fund" if "amount" in mapping else "stock"


def parse_holdings(df: pd.DataFrame, default_type: str = "auto"):
    """解析为项目内部持仓结构。

    返回 (rows, errors, mapping)。rows 中：
    - 股票: {"type","code","name","buy_price","shares"}
    - 基金: {"type","code","name","buy_nav","amount"}
    """
    mapping = detect_columns(df.columns)
    if "code" not in mapping:
        raise ValueError(
            "没有找到代码列。支持的表头：代码 / 基金代码 / 股票代码 / 证券代码"
        )

    rows = []
    errors = []

    for index, row in df.iterrows():
        line = index + 2  # 表头占第 1 行
        raw_code = row.get(mapping["code"])
        code = normalize_code(raw_code)
        if len(code) != 6:
            errors.append(f"第 {line} 行：代码格式不正确（{raw_code}）")
            continue

        name = ""
        if "name" in mapping:
            name = str(row.get(mapping["name"], "")).strip()
            if name.lower() == "nan":
                name = ""

        raw_type = row.get(mapping["type"], "") if "type" in mapping else ""
        holding_type = _infer_type(raw_type, name, mapping, default_type)

        price = _num(row.get(mapping["price"])) if "price" in mapping else None
        shares = _num(row.get(mapping["shares"])) if "shares" in mapping else None
        amount = _num(row.get(mapping["amount"])) if "amount" in mapping else None

        if price is None or price <= 0:
            errors.append(f"第 {line} 行：买入价/净值无效（{row.get(mapping.get('price', ''), '')}）")
            continue

        if holding_type == "stock":
            if shares is None or shares <= 0:
                errors.append(f"第 {line} 行：股票数量无效")
                continue
            rows.append({
                "type": "stock",
                "code": code,
                "name": name or code,
                "buy_price": round(price, 4),
                "shares": int(round(shares)),
            })
        else:
            if amount is None or amount <= 0:
                if shares and shares > 0:
                    amount = shares * price
                else:
                    errors.append(f"第 {line} 行：基金买入金额无效")
                    continue
            rows.append({
                "type": "fund",
                "code": code,
                "name": name or code,
                "buy_nav": round(price, 4),
                "amount": round(amount, 2),
            })

    return rows, errors, mapping


def merge_holdings(current: dict, rows: list[dict]):
    """把导入行合并进当前持仓（同类型同代码视为更新）。

    返回 (new_holdings, added, updated)。
    """
    stocks = {h["code"]: dict(h) for h in current.get("stocks", [])}
    funds = {h["code"]: dict(h) for h in current.get("funds", [])}
    added = 0
    updated = 0

    for row in rows:
        target = stocks if row["type"] == "stock" else funds
        code = row["code"]
        payload = {k: v for k, v in row.items() if k != "type"}
        if code in target:
            target[code].update(payload)
            updated += 1
        else:
            target[code] = payload
            added += 1

    return {"stocks": list(stocks.values()), "funds": list(funds.values())}, added, updated


def display_rows(rows: list[dict]) -> list[dict]:
    """预览表格（中文表头）。"""
    result = []
    for row in rows:
        is_stock = row["type"] == "stock"
        price = row.get("buy_price", row.get("buy_nav"))
        result.append({
            "类型": "股票" if is_stock else "基金",
            "代码": row["code"],
            "名称": row["name"],
            "买入价/净值": f"{price:.2f}" if is_stock else f"{price:.4f}",
            "数量": row.get("shares", ""),
            "金额": f"¥{row['amount']:,.0f}" if row.get("amount") else "",
        })
    return result


def to_sheet_payload(holdings: dict):
    """转成 sheets_db.add_user_holdings 需要的 funds/stocks 结构。"""
    funds = [
        {
            "code": h["code"],
            "name": h["name"],
            "alert_change_pct": 3,
            "alert_nav_below": 0,
        }
        for h in holdings.get("funds", [])
    ]
    stocks = [
        {
            "code": h["code"],
            "name": h["name"],
            "alert_change_pct": 5,
            "alert_below": 0,
        }
        for h in holdings.get("stocks", [])
    ]
    return funds, stocks
