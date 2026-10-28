"""截图识图导入 - 调用 DeepSeek 视觉模型提取持仓。

养基宝式流程：上传持仓截图 → 识别基金/股票 → 用户核对 → 导入。
不依赖额外 OCR 服务，直接复用项目已有的 Anthropic 兼容接口。
"""
from __future__ import annotations

import base64
import json
import math
import re
from typing import Any

import anthropic

from config_loader import get_model
from data_api import api_fund_valuation, api_search_fund, api_search_stock
from holdings_import import normalize_code

MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

SYSTEM_PROMPT = """你是一个基金/股票持仓截图识别器。
用户会给你一张来自支付宝、天天基金、腾讯理财通或雪球的“持有/持仓”页面截图。

任务：提取每一只基金或股票，忽略账户总资产、当日收益、累计收益、按钮、广告和合计行。
只输出一个 JSON 对象，不要 Markdown，不要解释：
{
  "items": [
    {
      "type": "fund 或 stock",
      "code": "6位数字或 null",
      "name": "名称",
      "shares": 数字或 null,
      "cost_nav": 数字或 null,
      "market_value": 数字或 null,
      "profit": 数字或 null,
      "confidence": 0 到 1
    }
  ],
  "warnings": ["识别不确定的地方"]
}

字段说明：
- code：只填截图中明确可见的 6 位代码；看不清就填 null，禁止猜测。
- shares：持有份额 / 持有数量。
- cost_nav：成本价 / 成本净值 / 买入净值；没有就填 null。
- market_value：持有金额 / 持仓市值；没有就填 null。
- profit：持有收益 / 浮动盈亏；没有就填 null。
- 数字去掉 ¥、%、千分位；看不清就填 null。
- 同一只基金只输出一次，不要输出汇总行。"""


def media_type_for(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return MEDIA_TYPES.get(ext, "image/png")


def parse_json_payload(text: str) -> dict:
    """从模型输出里取出 JSON，兼容 ```json 包裹和前后解释文字。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("模型没有返回内容")

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型返回中没有 JSON 对象")
    return json.loads(text[start:end + 1])


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = text.replace(",", "").replace("¥", "").replace("￥", "")
    text = text.replace("元", "").replace("%", "").replace("份", "")
    if not text or text.lower() in ("nan", "none", "-", "--", "暂无"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick(item: dict, *keys, default=None):
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


FUND_HINTS = ("基金", "etf", "lof", "qdii", "混合", "债券", "指数", "联接", "货币")


def _infer_type(raw_type, name: str) -> str:
    text = str(raw_type or "").lower()
    name_text = str(name or "").lower()
    if any(hint in name_text for hint in FUND_HINTS):
        return "fund"
    if text in ("stock", "股票") or "股票" in text:
        return "stock"
    return "fund"


def build_rows(payload: dict) -> tuple[list[dict], list[str]]:
    """把模型 JSON 转成项目内部的持仓结构，并给出需要人工确认的提示。"""
    if isinstance(payload, list):
        items = payload
        warnings = []
    else:
        items = (
            payload.get("items")
            or payload.get("holdings")
            or payload.get("funds")
            or []
        )
        raw_warnings = payload.get("warnings") or []
        if isinstance(raw_warnings, str):
            raw_warnings = [raw_warnings]
        warnings = [str(w) for w in raw_warnings if str(w).strip()]

    if not isinstance(items, list):
        return [], warnings + ["模型返回的 items 不是数组"]

    rows: list[dict] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue

        name = str(_pick(item, "name", "基金名称", "股票名称", "名称", default="") or "").strip()
        code = normalize_code(_pick(item, "code", "基金代码", "股票代码", "代码"))
        shares = _num(_pick(item, "shares", "持有份额", "份额", "持有数量", "数量"))
        cost_nav = _num(_pick(item, "cost_nav", "成本净值", "成本价", "买入净值", "持仓成本"))
        market_value = _num(_pick(item, "market_value", "持有金额", "持仓市值", "市值", "金额"))
        profit = _num(_pick(item, "profit", "持有收益", "浮动盈亏", "收益"))
        holding_type = _infer_type(
            _pick(item, "type", "类型"), name
        )

        note = ""
        if not code:
            note = "缺代码，请补全"

        def add_note(extra: str) -> str:
            return f"{note}；{extra}" if note else extra

        if holding_type == "stock":
            price = cost_nav
            if price is None and shares and market_value:
                price = market_value / shares
                note = add_note("按市值/数量估算")
            if not shares or shares <= 0 or price is None or price <= 0:
                warnings.append(f"第 {index} 条 {name or code}：缺少数量或成本价，已跳过")
                continue
            rows.append({
                "type": "stock",
                "code": code,
                "name": name or code,
                "buy_price": round(price, 4),
                "shares": int(round(shares)),
                "note": note,
            })
            continue

        amount = None
        buy_nav = None
        if shares and shares > 0 and cost_nav and cost_nav > 0:
            amount = shares * cost_nav
            buy_nav = cost_nav
        elif shares and shares > 0 and market_value and profit is not None:
            amount = market_value - profit
            buy_nav = amount / shares if amount > 0 else None
            note = add_note("按市值/收益倒推成本")
        elif shares and shares > 0 and market_value and market_value > 0:
            amount = market_value
            buy_nav = market_value / shares
            note = add_note("无成本价，按市值估算")
        elif cost_nav and cost_nav > 0 and market_value and market_value > 0:
            amount = market_value
            buy_nav = cost_nav
            note = add_note("缺份额，按市值估算")

        if not amount or amount <= 0 or not buy_nav or buy_nav <= 0:
            if market_value and market_value > 0 and profit is not None:
                rows.append({
                    "type": "fund",
                    "code": code,
                    "name": name or code,
                    "buy_nav": None,
                    "amount": None,
                    "market_value": round(market_value, 2),
                    "profit": round(profit, 2),
                    "note": add_note("只有市值和收益，导入时按最新净值估算"),
                })
            else:
                warnings.append(f"第 {index} 条 {name or code}：成本/份额信息不足，已跳过")
            continue

        rows.append({
            "type": "fund",
            "code": code,
            "name": name or code,
            "buy_nav": round(buy_nav, 4),
            "amount": round(amount, 2),
            "market_value": round(market_value, 2) if market_value else None,
            "profit": round(profit, 2) if profit is not None else None,
            "note": note,
        })

    return rows, warnings


def extract_holdings(
    image_bytes: bytes,
    filename: str,
    platform: str,
    api_key: str,
    model: str | None = None,
) -> tuple[dict, str]:
    """调用视觉模型，返回 (解析后的 JSON, 原始文本)。"""
    if not api_key:
        raise RuntimeError("未配置 API Key，无法识别截图")

    model = model or get_model("vision")
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url="https://api.deepseek.com/anthropic",
    )
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"截图来源平台：{platform}。"
                        "请识别其中每一只基金/股票，严格按系统要求返回 JSON。"
                    ),
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type_for(filename),
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
            ],
        }],
    )

    text = "".join(
        block.text for block in response.content
        if getattr(block, "type", "") == "text"
    )
    if not text.strip():
        block_types = [getattr(block, "type", "?") for block in response.content]
        raise RuntimeError(f"模型没有返回文本内容（blocks: {block_types}）")
    return parse_json_payload(text), text


def recognize(
    image_bytes: bytes,
    filename: str,
    platform: str,
    api_key: str,
) -> tuple[list[dict], list[str], str]:
    """截图 → 持仓行。返回 (rows, warnings, 原始文本)。"""
    payload, raw_text = extract_holdings(
        image_bytes, filename, platform, api_key
    )
    rows, warnings = build_rows(payload)
    return rows, warnings, raw_text


def _resolve_code(name: str, holding_type: str) -> str:
    """截图没有代码时，按名称查代码；只接受完全匹配或包含匹配的第一条。"""
    if not name:
        return ""
    try:
        results = (
            api_search_stock(name) if holding_type == "stock"
            else api_search_fund(name)
        )
    except Exception:
        return ""
    if not results or (isinstance(results[0], dict) and "error" in results[0]):
        return ""
    for item in results:
        if str(item.get("name", "")) == name:
            return str(item.get("code", ""))
    for item in results:
        item_name = str(item.get("name", ""))
        if item_name and (name in item_name or item_name in name):
            return str(item.get("code", ""))
    return ""


def enrich_rows(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """用基金最新净值，把“只有市值和收益”的行补成 成本/份额/净值。

    支付宝等平台的持有列表常常只显示持有金额和收益；用
    份额 = 当前市值 / 最新净值、成本 = 当前市值 - 收益 反推。
    净值有延迟时会有少量误差，备注里会写明。
    """
    out = []
    warnings = []
    for index, item in enumerate(rows, 1):
        row = dict(item)

        # 先按名称补代码（截图里经常只有基金名，没有 6 位代码）
        if not row.get("code") and row.get("name"):
            resolved = _resolve_code(row["name"], row.get("type", "fund"))
            if resolved:
                row["code"] = resolved
                row["note"] = row.get("note", "").replace("缺代码，请补全", "").strip("；")

        if (
            row.get("type") == "fund"
            and (not row.get("buy_nav") or not row.get("amount"))
            and row.get("market_value")
            and row.get("profit") is not None
        ):
            code = row.get("code")
            if not code:
                warnings.append(f"第 {index} 条 {row.get('name', '')}：缺少代码，无法估算成本")
                out.append(row)
                continue
            val = api_fund_valuation(code)
            nav = val.get("nav") if val else None
            if not nav or nav <= 0:
                warnings.append(f"第 {index} 条 {row.get('name', code)}：取不到净值，无法估算成本")
                out.append(row)
                continue
            market_value = float(row["market_value"])
            cost_amount = market_value - float(row["profit"])
            if cost_amount <= 0:
                warnings.append(f"第 {index} 条 {row.get('name', code)}：收益大于市值，数据异常")
                out.append(row)
                continue
            shares = market_value / nav
            row["buy_nav"] = round(cost_amount / shares, 4)
            row["amount"] = round(cost_amount, 2)
            base_note = row.get("note", "")
            row["note"] = (
                f"{base_note}；按净值 {nav:.4f} 估算" if base_note
                else f"按净值 {nav:.4f} 估算"
            )
        out.append(row)
    return out, warnings


def editor_to_rows(df) -> tuple[list[dict], list[str]]:
    """把 st.data_editor 编辑后的表格转回内部持仓结构。"""
    rows = []
    errors = []
    for i, row in df.iterrows():
        code = normalize_code(row.get("代码"))
        name = str(row.get("名称") or "").strip()
        if len(code) != 6:
            errors.append(f"第 {i + 1} 行：代码必须是 6 位数字")
            continue

        price = _num(row.get("买入价/净值"))
        amount = _num(row.get("金额"))
        market_value = _num(row.get("当前市值"))
        profit = _num(row.get("收益"))

        if (not price or price <= 0) and not (market_value and profit is not None):
            errors.append(f"第 {i + 1} 行：买入价/净值无效")
            continue

        if str(row.get("类型") or "") == "股票":
            shares = _num(row.get("份额"))
            if not shares or shares <= 0:
                errors.append(f"第 {i + 1} 行：股票数量无效")
                continue
            rows.append({
                "type": "stock", "code": code, "name": name or code,
                "buy_price": round(price, 4),
                "shares": int(round(shares)),
            })
        elif price and price > 0 and amount and amount > 0:
            rows.append({
                "type": "fund", "code": code, "name": name or code,
                "buy_nav": round(price, 4),
                "amount": round(amount, 2),
            })
        elif market_value and market_value > 0 and profit is not None:
            rows.append({
                "type": "fund", "code": code, "name": name or code,
                "buy_nav": None, "amount": None,
                "market_value": round(market_value, 2),
                "profit": round(profit, 2),
            })
        else:
            errors.append(f"第 {i + 1} 行：基金金额无效")
            continue
    return rows, errors


def _fmt(value, digits: int = 2) -> str:
    """表格里空值显示为空白；数字用固定小数位。"""
    if value is None:
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def rows_for_editor(rows: list[dict]) -> list[dict]:
    """给 st.data_editor 的预览数据（全部用文本，空值不会显示 None）。"""
    result = []
    for row in rows:
        is_stock = row["type"] == "stock"
        result.append({
            "类型": "股票" if is_stock else "基金",
            "代码": row["code"],
            "名称": row["name"],
            "买入价/净值": _fmt(row.get("buy_price", row.get("buy_nav")), 4),
            "份额": _fmt(row.get("shares"), 2) if is_stock else "",
            "金额": _fmt(row.get("amount")),
            "当前市值": _fmt(row.get("market_value")),
            "收益": _fmt(row.get("profit")),
        })
    return result
