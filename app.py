"""
金融研报 Agent - Streamlit 网页版（真实数据）
覆盖：全部 A 股 + 支付宝/天天基金所有公募基金

运行方式: python3 -m streamlit run finance_app.py
"""

from __future__ import annotations

import os
import streamlit as st
import anthropic
import json
import requests
import re
from datetime import datetime


def get_api_key() -> str:
    """优先从 Streamlit secrets 读取，其次从环境变量"""
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")

# ═══════════════════════════════════════════════
# 页面配置
# ═══════════════════════════════════════════════

st.set_page_config(
    page_title="金融研报 Agent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 金融研报 Agent")
st.caption("覆盖全部 A 股（5000+）和支付宝/天天基金全部公募基金（10000+）")

# ═══════════════════════════════════════════════
# 数据 API 层
# ═══════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.eastmoney.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def api_search_stock(keyword: str) -> list[dict]:
    """搜索 A 股股票"""
    url = "https://searchadapter.eastmoney.com/api/suggest/get"
    params = {
        "input": keyword, "type": "14",
        "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": 5,
    }
    try:
        r = SESSION.get(url, params=params, timeout=8)
        data = r.json()
        results = []
        for item in data.get("QuotationCodeTable", {}).get("Data", []):
            if item.get("Classify") == "AStock":
                results.append({
                    "code": item["Code"],
                    "name": item["Name"],
                    "market": item.get("MarketType", ""),
                })
        return results
    except Exception as e:
        return [{"error": str(e)}]


SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
SINA_SESSION = requests.Session()
SINA_SESSION.headers.update(SINA_HEADERS)


def api_stock_quote(code: str) -> dict | None:
    """获取个股实时行情（新浪财经主源 + 东方财富备源）"""
    # 主数据源：新浪财经（全部A股稳定可用）
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = SINA_SESSION.get(f"https://hq.sinajs.cn/list={prefix}{code}", timeout=8)
        r.encoding = "gbk"
        match = re.search(r'"(.+)"', r.text)
        if match:
            parts = match.group(1).split(",")
            if len(parts) >= 10 and parts[0]:
                price = float(parts[3])
                prev_close = float(parts[2])
                change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
                return {
                    "name": parts[0],
                    "code": code,
                    "price": price,
                    "open": float(parts[1]),
                    "prev_close": prev_close,
                    "high": float(parts[4]),
                    "low": float(parts[5]),
                    "volume_hands": int(float(parts[8]) / 100),
                    "amount": float(parts[9]),
                    "turnover_rate": 0,
                    "market_cap": 0,
                    "change_amount": price - prev_close,
                    "change_pct": round(change_pct, 2),
                }
    except Exception:
        pass

    # 备数据源：东方财富
    market = "1" if code.startswith("6") else "0"
    try:
        r = SESSION.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": f"{market}.{code}",
                    "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f170,f171"},
            timeout=8,
        )
        data = r.json().get("data", {})
        if data:
            return {
                "name": data.get("f58", ""),
                "code": data.get("f57", code),
                "price": data.get("f43", 0) / 100 if data.get("f43") else 0,
                "high": data.get("f44", 0) / 100 if data.get("f44") else 0,
                "low": data.get("f45", 0) / 100 if data.get("f45") else 0,
                "open": data.get("f46", 0) / 100 if data.get("f46") else 0,
                "prev_close": data.get("f60", 0) / 100 if data.get("f60") else 0,
                "volume_hands": data.get("f47", 0),
                "amount": data.get("f48", 0),
                "turnover_rate": data.get("f116", 0) / 100 if data.get("f116") else 0,
                "market_cap": data.get("f117", 0),
                "change_amount": data.get("f170", 0) / 100 if data.get("f170") else 0,
                "change_pct": data.get("f171", 0) / 100 if data.get("f171") else 0,
            }
    except Exception:
        pass

    return None


def api_stock_kline(code: str, days: int = 30) -> list[dict]:
    """获取个股历史 K 线"""
    market = "1" if code.startswith("6") else "0"
    secid = f"{market}.{code}"
    try:
        r = SESSION.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": "101", "fqt": "1", "end": "20500101", "lmt": days,
            },
            timeout=10,
        )
        klines = r.json().get("data", {}).get("klines", [])
        results = []
        for line in klines:
            parts = line.split(",")
            results.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": int(parts[5]),
                "amount": float(parts[6]),
            })
        return results
    except Exception:
        return []


def api_search_fund(keyword: str) -> list[dict]:
    """搜索公募基金（含QDII海外基金）"""
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    params = {"m": "1", "key": keyword}
    try:
        r = SESSION.get(url, params=params, timeout=8)
        text = r.text
        # 兼容 JSONP 和纯 JSON 两种返回
        data = None
        match = re.search(r"\((.+)\)", text)
        if match:
            data = json.loads(match.group(1))
        elif text.startswith("{"):
            data = json.loads(text)
        if not data:
            return []
        results = []
        for item in data.get("Datas", [])[:5]:
            info = item.get("FundBaseInfo", {})
            if info.get("FCODE"):
                results.append({
                    "code": info.get("FCODE", ""),
                    "name": info.get("SHORTNAME", ""),
                    "type": info.get("FTYPE", ""),
                    "company": info.get("JJGS", ""),
                    "nav": info.get("DWJZ", ""),
                    "is_buyable": info.get("ISBUY", "") == "1",
                })
        return results
    except Exception:
        return []


def api_fund_valuation(code: str) -> dict | None:
    """获取基金实时估值"""
    url = f"https://fundgz.1234567.com.cn/js/{code}.js"
    try:
        r = SESSION.get(url, timeout=8)
        text = r.text
        match = re.search(r"jsonpgz\((.+)\)", text)
        if not match:
            return None
        data = json.loads(match.group(1))
        return {
            "code": data.get("fundcode", code),
            "name": data.get("name", ""),
            "nav_date": data.get("jzrq", ""),
            "nav": float(data.get("dwjz", 0)),
            "estimated_nav": float(data.get("gsz", 0)),
            "estimated_change_pct": float(data.get("gszzl", 0)),
            "estimate_time": data.get("gztime", ""),
        }
    except Exception:
        return None


def api_fund_nav_history(code: str, count: int = 10) -> list[dict]:
    """获取基金历史净值"""
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    params = {"fundCode": code, "pageIndex": 1, "pageSize": count}
    headers = {**HEADERS, "Referer": "https://fundf10.eastmoney.com/"}
    try:
        r = SESSION.get(url, params=params, headers=headers, timeout=8)
        items = r.json().get("Data", {}).get("LSJZList", [])
        results = []
        for item in items:
            results.append({
                "date": item.get("FSRQ", ""),
                "nav": float(item.get("DWJZ", 0)),
                "acc_nav": float(item.get("LJJZ", 0)),
                "daily_change_pct": float(item.get("JZZZL", 0)) if item.get("JZZZL") else 0,
            })
        return results
    except Exception:
        return []


def api_fund_info(code: str) -> dict | None:
    """获取基金基本信息（规模、经理、成立时间等）"""
    # 用搜索接口查基金代码
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    params = {"m": "1", "key": code}
    try:
        r = SESSION.get(url, params=params, timeout=8)
        match = re.search(r"\((.+)\)", r.text)
        if not match:
            return None
        data = json.loads(match.group(1))
        for item in data.get("Datas", []):
            info = item.get("FundBaseInfo", {})
            if info.get("FCODE") == code:
                return {
                    "code": info.get("FCODE", code),
                    "name": info.get("SHORTNAME", ""),
                    "type": info.get("FTYPE", ""),
                    "company": info.get("JJGS", ""),
                    "manager": info.get("JJJL", ""),
                    "min_subscribe": info.get("MINSG", 0),
                    "is_buyable": info.get("ISBUY", "") == "1",
                }
        return None
    except Exception:
        return None


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
        for k in klines[-10:]:  # 最近10条
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

    model = "deepseek-v4-flash" if fast_mode else "deepseek-v4-pro"

    messages = [{"role": "user", "content": user_question}]
    system_prompt = (
        "你是一位专业的金融分析师助手，精通A股和公募基金分析。\n\n"
        "核心原则：一次性并行调用所有需要的工具，不要分步！\n"
        "如果用户提到了股票名称（你不知道代码），请在同一轮同时调用 search_stock + get_stock_quote + get_stock_kline，"
        "search_stock 用名称关键词，股票代码字段可以先用空字符串或从搜索中推断。"
        "如果用户明确给了股票代码，直接并行调用 get_stock_quote 和 get_stock_kline。\n\n"
        "同理，分析基金时并行调用 get_fund_info + get_fund_valuation + get_fund_nav_history。\n\n"
        "分析股票输出：行情概况、近期走势（技术面）、关键价格位、成交活跃度、操作建议，用表格呈现关键数据。\n"
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


# ═══════════════════════════════════════════════
# 侧边栏
# ═══════════════════════════════════════════════

with st.sidebar:
    st.header("📈 快速查询")

    with st.expander("🔥 热门股票", expanded=True):
        stocks = {
            "贵州茅台 (600519)": "帮我全面分析一下贵州茅台",
            "宁德时代 (300750)": "宁德时代最近走势怎么样，适合入手吗？",
            "比亚迪 (002594)": "比亚迪目前的行情和技术面如何？",
            "中国平安 (601318)": "中国平安现在的估值水平怎么样？",
        }
        for label, question in stocks.items():
            if st.button(label, use_container_width=True):
                st.session_state.question = question

    with st.expander("📊 热门基金", expanded=False):
        funds = {
            "天弘沪深300ETF联接A (000961)": "帮我分析一下天弘沪深300ETF联接A这只基金000961",
            "招商中证白酒指数 (161725)": "分析招商中证白酒指数基金161725，现在适合定投吗？",
            "易方达蓝筹精选 (005827)": "易方达蓝筹精选005827这只基金表现怎么样？",
            "华夏成长混合 (000001)": "帮我看看华夏成长混合000001的净值走势",
        }
        for label, question in funds.items():
            if st.button(label, use_container_width=True):
                st.session_state.question = question

    st.divider()
    st.caption("✅ 覆盖 A 股 5000+ | 基金 10000+")
    st.caption("📡 数据源：东方财富 / 天天基金")

# ═══════════════════════════════════════════════
# 主区域
# ═══════════════════════════════════════════════

col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    user_input = st.text_input(
        "输入你的问题",
        placeholder="分析股票直接说名称或代码，如：宁德时代最近走势怎么样？\n分析基金加上代码，如：帮我看看000001这只基金",
        key="question",
        label_visibility="collapsed",
    )
with col2:
    fast_mode = st.toggle("⚡ 快速模式", value=True, help="快速模式用 Flash 模型，秒级响应；关闭用 Pro 模型，分析更详细但稍慢")
with col3:
    analyze_btn = st.button("🔍 开始分析", type="primary", use_container_width=True)

if analyze_btn and user_input:
    with st.spinner(f"Agent 正在分析... (模型: deepseek-v4-{'flash' if fast_mode else 'pro'})"):
        status_area = st.empty()
        result = run_agent(user_input, status_area, fast_mode=fast_mode)
        status_area.empty()

    st.divider()
    st.markdown(result)

# ═══════════════════════════════════════════════
# 底部
# ═══════════════════════════════════════════════

st.divider()
st.caption(
    "⚠️ 以上分析基于公开数据，不构成投资建议。股市有风险，入市需谨慎。"
    " | 数据来源：东方财富 / 天天基金 | 模型：DeepSeek V4"
)
