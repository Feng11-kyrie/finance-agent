"""Agent 核心 - 工具定义、工具执行与 Agent 循环。

不依赖 Streamlit（get_api_key 懒加载），可单独测试。
"""
from __future__ import annotations

import json
import os

import anthropic

from config_loader import get_model
from data_api import (
    api_search_stock,
    api_stock_quote,
    api_stock_kline,
    api_search_fund,
    api_fund_valuation,
    api_fund_nav_history,
    api_fund_info,
)


def get_api_key() -> str:
    """优先从 Streamlit secrets 读取，其次从环境变量。"""
    try:
        import streamlit as st
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════
# 工具定义
# ═══════════════════════════════════════════════

TOOLS = [
    {
        "name": "search_stock",
        "description": "根据股票名称或代码关键词搜索A股。返回匹配的股票代码和名称。不知道代码时必须先调用此工具。如搜索'宁德'返回宁德时代(300750)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "股票名称关键词或代码片段，如 茅台、宁德、600519"}
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_stock_quote",
        "description": "获取股票实时行情：最新价、涨跌幅、最高/最低/开盘/昨收、成交量、换手率、总市值。参数 stock_code 为6位代码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "6位A股代码，如 600519"}
            },
            "required": ["stock_code"],
        },
    },
    {
        "name": "get_stock_kline",
        "description": "获取股票近30个交易日的日K线（开高低收+成交量+成交额），用于技术分析。参数 stock_code 为6位代码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "6位A股代码"}
            },
            "required": ["stock_code"],
        },
    },
    {
        "name": "search_fund",
        "description": "搜索公募基金（覆盖支付宝/天天基金全部基金）。根据关键词返回匹配的基金代码、名称、类型。如搜索'沪深300'返回相关沪深300指数基金。",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "基金名称关键词或代码，如 沪深300、白酒、000001"}
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_fund_valuation",
        "description": "获取基金实时估值和净值数据：当前估算净值、估算涨跌幅、上一交易日净值。参数 fund_code 为6位基金代码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "description": "6位基金代码，如 000001"}
            },
            "required": ["fund_code"],
        },
    },
    {
        "name": "get_fund_nav_history",
        "description": "获取基金近10个交易日的净值走势（单位净值+累计净值+日涨跌幅）。用于分析基金近期表现。参数 fund_code 为6位基金代码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "description": "6位基金代码"}
            },
            "required": ["fund_code"],
        },
    },
    {
        "name": "get_fund_info",
        "description": "获取基金详细信息：全称、类型、基金公司、基金经理、起购金额、是否可申购。参数 fund_code 为6位基金代码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "description": "6位基金代码"}
            },
            "required": ["fund_code"],
        },
    },
]


# ═══════════════════════════════════════════════
# 工具执行
# ═══════════════════════════════════════════════

def execute_tool(name: str, params: dict) -> str:
    if name == "search_stock":
        results = api_search_stock(params["keyword"])
        if not results:
            return f"未找到与'{params['keyword']}'相关的A股"
        if isinstance(results[0], dict) and "error" in results[0]:
            return f"搜索出错: {results[0]['error']}"
        lines = [f"找到 {len(results)} 只相关股票:"]
        for s in results:
            lines.append(f"{s['code']} - {s['name']}")
        return "\n".join(lines)

    elif name == "get_stock_quote":
        data = api_stock_quote(params["stock_code"])
        if not data:
            return f"未获取到股票 {params['stock_code']} 的行情数据"
        sign = "+" if data["change_pct"] >= 0 else ""
        return json.dumps({
            "股票名称": data["name"],
            "股票代码": data["code"],
            "最新价": f"{data['price']:.2f}元",
            "涨跌幅": f"{sign}{data['change_pct']:.2f}%",
            "涨跌额": f"{sign}{data['change_amount']:.2f}元",
            "今开": f"{data['open']:.2f}",
            "最高": f"{data['high']:.2f}",
            "最低": f"{data['low']:.2f}",
            "昨收": f"{data['prev_close']:.2f}",
            "成交量": f"{data['volume_hands']}手",
            "换手率": f"{data['turnover_rate']:.2f}%",
            "总市值": f"{data['market_cap']/1e8:.2f}亿" if data["market_cap"] else "N/A",
        }, ensure_ascii=False, indent=2)

    elif name == "get_stock_kline":
        klines = api_stock_kline(params["stock_code"], 30)
        if not klines:
            return f"未获取到股票 {params['stock_code']} 的K线数据"
        lines = ["日期        |  开盘   |  收盘   |  最高   |  最低   |  成交量(手) |  成交额(亿)"]
        for k in klines[-10:]:
            lines.append(
                f"{k['date']} | {k['open']:7.2f} | {k['close']:7.2f} | "
                f"{k['high']:7.2f} | {k['low']:7.2f} | "
                f"{k['volume']:>10} | {k['amount']/1e8:>8.2f}"
            )
        lines.append(f"\n(共获取 {len(klines)} 条K线，以上为最近10条)")
        return "\n".join(lines)

    elif name == "search_fund":
        results = api_search_fund(params["keyword"])
        if not results:
            return f"未找到与'{params['keyword']}'相关的基金"
        lines = [f"找到 {len(results)} 只相关基金:"]
        for f in results:
            status = "可申购" if f["is_buyable"] else "暂停申购"
            lines.append(f"{f['code']} - {f['name']} | {f['type']} | {f['company']} | {status}")
        return "\n".join(lines)

    elif name == "get_fund_valuation":
        data = api_fund_valuation(params["fund_code"])
        if not data:
            return f"未获取到基金 {params['fund_code']} 的估值数据"
        sign = "+" if data["estimated_change_pct"] >= 0 else ""
        return json.dumps({
            "基金名称": data["name"],
            "基金代码": data["code"],
            "净值日期": data["nav_date"],
            "单位净值": f"{data['nav']:.4f}元",
            "估算净值": f"{data['estimated_nav']:.4f}元",
            "估算涨跌幅": f"{sign}{data['estimated_change_pct']:.2f}%",
            "估值时间": data["estimate_time"],
        }, ensure_ascii=False, indent=2)

    elif name == "get_fund_nav_history":
        history = api_fund_nav_history(params["fund_code"], 10)
        if not history:
            return f"未获取到基金 {params['fund_code']} 的净值历史"
        lines = ["日期      | 单位净值 | 累计净值 | 日涨跌幅"]
        for h in history:
            sign = "+" if h["daily_change_pct"] >= 0 else ""
            lines.append(
                f"{h['date']} | {h['nav']:>8.4f} | {h['acc_nav']:>8.4f} | "
                f"{sign}{h['daily_change_pct']:.2f}%"
            )
        return "\n".join(lines)

    elif name == "get_fund_info":
        data = api_fund_info(params["fund_code"])
        if not data:
            return f"未获取到基金 {params['fund_code']} 的详细信息"
        return json.dumps({
            "基金全称": data["name"],
            "基金代码": data["code"],
            "基金类型": data["type"],
            "基金公司": data["company"],
            "基金经理": data["manager"],
            "起购金额": f"{data['min_subscribe']}元",
            "申购状态": "可申购" if data["is_buyable"] else "暂停申购",
        }, ensure_ascii=False, indent=2)

    return "未知工具"


# ═══════════════════════════════════════════════
# Agent 循环
# ═══════════════════════════════════════════════

def run_agent(user_question: str, status_container, fast_mode: bool = True) -> str:
    api_key = get_api_key()
    if not api_key:
        return "❌ 未配置 API Key，请在 Streamlit Cloud 的 Settings → Secrets 中添加 `ANTHROPIC_API_KEY`"

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url="https://api.deepseek.com/anthropic",
    )

    model = get_model("pro" if not fast_mode else "fast")

    messages = [{"role": "user", "content": user_question}]
    system_prompt = (
        "你是一位专业的金融分析师助手，精通A股和公募基金分析。\n\n"
        "工具调用规则（务必遵守）：\n"
        "1. 当用户只给出【名称】而没有代码时，先只调用 search_stock 或 search_fund 获取6位代码。\n"
        "2. 拿到代码后，再并行调用行情/净值工具：\n"
        "   - 股票：get_stock_quote + get_stock_kline\n"
        "   - 基金：get_fund_info + get_fund_valuation + get_fund_nav_history\n"
        "3. 禁止在同一轮里同时调用“搜索”和“行情/净值”工具，因为行情工具需要搜索返回的代码。\n"
        "4. 如果用户已明确给出6位代码，可直接并行调用对应的行情/净值工具。\n\n"
        "分析股票输出：行情概况、近期走势（技术面）、关键价格位、成交活跃度、观察要点（仅供参考），用表格呈现关键数据。\n"
        "分析基金输出：基金概况、净值走势、近期表现、适合人群，用表格呈现关键数据。\n\n"
        "回复格式：Markdown，简洁有力，避免长段落。"
    )

    tool_call_log = []

    for _ in range(5):
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
        )

        messages.append({
            "role": "assistant",
            "content": response.content,
        })

        tool_uses = []
        text_parts = []

        for block in response.content:
            if block.type == "tool_use":
                tool_uses.append(block)
            elif block.type == "text" and block.text.strip():
                text_parts.append(block.text)

        if not tool_uses:
            return "".join(text_parts) or response.content[0].text

        tool_results = []
        for tu in tool_uses:
            params_str = json.dumps(tu.input, ensure_ascii=False)
            log_msg = f"🔧 {tu.name}({params_str})"
            tool_call_log.append(log_msg)

            result = execute_tool(tu.name, tu.input)
            # 截断过长结果
            display = result[:300] + "..." if len(result) > 300 else result
            tool_call_log.append(f"  └─ {display}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        status_container.code("\n".join(tool_call_log), language="text")

        messages.append({
            "role": "user",
            "content": tool_results,
        })

    return "分析超时，请重试"
