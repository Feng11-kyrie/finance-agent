"""
金融研报 Agent - Streamlit 网页版（真实数据）
覆盖：全部 A 股 + 支付宝/天天基金所有公募基金

运行方式: python3 -m streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from agent import run_agent
from config_loader import get_model
from data_api import api_stock_quote, api_fund_valuation

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
# 持仓管理
# ═══════════════════════════════════════════════

def init_holdings():
    """初始化持仓 session state"""
    if "holdings" not in st.session_state:
        st.session_state.holdings = {"stocks": [], "funds": []}


def add_stock_holding(code: str, name: str, buy_price: float, shares: int):
    st.session_state.holdings["stocks"].append({
        "code": code, "name": name,
        "buy_price": buy_price, "shares": shares,
    })


def add_fund_holding(code: str, name: str, buy_nav: float, amount: float):
    st.session_state.holdings["funds"].append({
        "code": code, "name": name,
        "buy_nav": buy_nav, "amount": amount,
    })


def remove_holding(htype: str, idx: int):
    if idx < len(st.session_state.holdings[htype]):
        st.session_state.holdings[htype].pop(idx)


def compute_stock_pnl(holding: dict, quote: dict | None) -> dict:
    """计算单支股票的盈亏"""
    if not quote:
        return {"error": "行情获取失败"}
    current_price = quote["price"]
    buy_price = holding["buy_price"]
    shares = holding["shares"]
    pnl = (current_price - buy_price) * shares
    pnl_pct = (current_price - buy_price) / buy_price * 100
    return {
        "name": quote.get("name", holding["name"]),
        "code": holding["code"],
        "buy_price": buy_price,
        "current_price": current_price,
        "shares": shares,
        "market_value": current_price * shares,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "change_today": quote.get("change_pct", 0),
    }


def compute_fund_pnl(holding: dict, valuation: dict | None) -> dict:
    """计算单支基金的盈亏"""
    if not valuation:
        return {"error": "估值获取失败"}
    current_nav = valuation["estimated_nav"] or valuation["nav"]
    buy_nav = holding["buy_nav"]
    amount = holding["amount"]
    units = amount / buy_nav
    pnl = (current_nav - buy_nav) * units
    pnl_pct = (current_nav - buy_nav) / buy_nav * 100
    return {
        "name": valuation.get("name", holding["name"]),
        "code": holding["code"],
        "buy_nav": buy_nav,
        "current_nav": current_nav,
        "amount": amount,
        "market_value": current_nav * units,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "change_today": valuation.get("estimated_change_pct", 0),
    }


def run_portfolio_check(status_container) -> list:
    """运行持仓监控，返回所有持仓的 P&L"""
    results = {"stocks": [], "funds": [], "alerts": []}
    holdings = st.session_state.holdings

    for h in holdings["stocks"]:
        status_container.text(f"检查股票: {h['name']}({h['code']})...")
        quote = api_stock_quote(h["code"])
        pnl = compute_stock_pnl(h, quote)
        results["stocks"].append(pnl)
        # 检查告警条件
        if "error" not in pnl:
            if pnl["pnl_pct"] <= -5:
                results["alerts"].append(
                    f"🔴 {pnl['name']}({pnl['code']}) 亏损 {pnl['pnl_pct']:.1f}%，"
                    f"当前价 ¥{pnl['current_price']:.2f}，建议关注"
                )
            elif pnl["pnl_pct"] >= 10:
                results["alerts"].append(
                    f"🟢 {pnl['name']}({pnl['code']}) 盈利 {pnl['pnl_pct']:.1f}%，"
                    f"当前价 ¥{pnl['current_price']:.2f}，可考虑止盈"
                )
            if abs(pnl["change_today"]) >= 5:
                direction = "大涨" if pnl["change_today"] > 0 else "大跌"
                results["alerts"].append(
                    f"⚠️ {pnl['name']}({pnl['code']}) 今日{direction} {pnl['change_today']:+.1f}%"
                )

    for h in holdings["funds"]:
        status_container.text(f"检查基金: {h['name']}({h['code']})...")
        val = api_fund_valuation(h["code"])
        pnl = compute_fund_pnl(h, val)
        results["funds"].append(pnl)
        if "error" not in pnl:
            if pnl["pnl_pct"] <= -5:
                results["alerts"].append(
                    f"🔴 {pnl['name']}({pnl['code']}) 亏损 {pnl['pnl_pct']:.1f}%，建议关注"
                )

    return results


# ═══════════════════════════════════════════════
# 页面初始化
# ═══════════════════════════════════════════════

init_holdings()

# ── 侧边栏 ─────────────────────────────────────

with st.sidebar:
    st.header("📈 快速查询")

    with st.expander("🔥 热门股票", expanded=False):
        stocks = {
            "贵州茅台 (600519)": "帮我全面分析一下贵州茅台",
            "宁德时代 (300750)": "宁德时代最近走势怎么样，适合入手吗？",
            "比亚迪 (002594)": "比亚迪目前的行情和技术面如何？",
            "中国平安 (601318)": "中国平安现在的估值水平怎么样？",
        }
        for label, question in stocks.items():
            if st.button(label, use_container_width=True, key=f"stock_{label[:10]}"):
                st.session_state.question = question

    with st.expander("📊 热门基金", expanded=False):
        funds = {
            "天弘沪深300联接A (000961)": "帮我分析一下天弘沪深300ETF联接A这只基金000961",
            "招商中证白酒 (161725)": "分析招商中证白酒指数基金161725，现在适合定投吗？",
            "易方达蓝筹 (005827)": "易方达蓝筹精选005827这只基金表现怎么样？",
            "华夏成长 (000001)": "帮我看看华夏成长混合000001的净值走势",
        }
        for label, question in funds.items():
            if st.button(label, use_container_width=True, key=f"fund_{label[:10]}"):
                st.session_state.question = question

    st.divider()

    # ── 我的持仓 ──
    st.header("📋 我的持仓")

    tab1, tab2 = st.tabs(["➕ 添加", "📋 列表"])

    with tab1:
        htype = st.selectbox("类型", ["股票", "基金"], key="htype")
        hcode = st.text_input("代码", placeholder="如 600519 或 000001", key="hcode")
        hname = st.text_input("名称（可选）", placeholder="自动获取", key="hname")
        if htype == "股票":
            hprice = st.number_input("买入价（元）", min_value=0.01, value=100.0, step=0.01, key="hprice")
            hshares = st.number_input("数量（股）", min_value=1, value=100, step=100, key="hshares")
        else:
            hprice = st.number_input("买入净值（元）", min_value=0.0001, value=1.0, step=0.01, key="hprice_fund")
            hshares = st.number_input("买入金额（元）", min_value=1, value=1000, step=100, key="hshares_fund")

        if st.button("✅ 添加到持仓", use_container_width=True, type="primary"):
            if hcode and len(hcode) == 6:
                if not hname:
                    # 尝试自动获取名称
                    if htype == "股票":
                        q = api_stock_quote(hcode)
                        hname = q["name"] if q else hcode
                    else:
                        v = api_fund_valuation(hcode)
                        hname = v["name"] if v else hcode
                if htype == "股票":
                    add_stock_holding(hcode, hname, hprice, int(hshares))
                else:
                    add_fund_holding(hcode, hname, hprice, hshares)
                st.success(f"已添加: {hname}({hcode})")
                st.rerun()
            else:
                st.error("请输入6位代码")

    with tab2:
        holdings_data = st.session_state.holdings
        total_stocks = len(holdings_data["stocks"])
        total_funds = len(holdings_data["funds"])

        if total_stocks == 0 and total_funds == 0:
            st.caption("暂无持仓，点击 「➕ 添加」")
        else:
            st.caption(f"📊 {total_stocks} 支股票 | {total_funds} 支基金")

            for i, h in enumerate(holdings_data["stocks"]):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"📈 {h['name']}({h['code']})")
                    st.text(f"   买入 ¥{h['buy_price']} × {h['shares']}股")
                with col2:
                    if st.button("✕", key=f"del_s_{i}"):
                        remove_holding("stocks", i)
                        st.rerun()

            for i, h in enumerate(holdings_data["funds"]):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"📊 {h['name']}({h['code']})")
                    st.text(f"   买入净值 ¥{h['buy_nav']} 金额 ¥{h['amount']}")
                with col2:
                    if st.button("✕", key=f"del_f_{i}"):
                        remove_holding("funds", i)
                        st.rerun()

            if st.button("🗑️ 清空全部", use_container_width=True):
                st.session_state.holdings = {"stocks": [], "funds": []}
                st.rerun()

    st.divider()
    st.caption("✅ A 股 5000+ | 基金 10000+")
    st.caption("📡 东方财富 / 天天基金")

# ═══════════════════════════════════════════════
# 主区域
# ═══════════════════════════════════════════════

tab_analyze, tab_monitor, tab_register = st.tabs(["🔍 智能分析", "📋 持仓监控", "📝 注册推送"])

# ── Tab 1: 智能分析 ───────────────────────────

with tab_analyze:
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
        with st.spinner(f"Agent 正在分析... (模型: {get_model('pro' if not fast_mode else 'fast')})"):
            status_area = st.empty()
            result = run_agent(user_input, status_area, fast_mode=fast_mode)
            status_area.empty()

        st.divider()
        st.markdown(result)

# ── Tab 2: 持仓监控 ───────────────────────────

with tab_monitor:
    st.subheader("📋 我的持仓监控")

    holdings_data = st.session_state.holdings
    has_holdings = len(holdings_data["stocks"]) > 0 or len(holdings_data["funds"]) > 0

    if not has_holdings:
        st.info("👈 在左侧边栏 「📋 我的持仓」→「➕ 添加」先添加你的持仓，然后回到这里点 「🔔 一键监控」")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            monitor_btn = st.button("🔔 一键监控", type="primary", use_container_width=True)
        with col2:
            st.caption(f"当前监控 {len(holdings_data['stocks'])} 支股票 + {len(holdings_data['funds'])} 支基金")

        if monitor_btn:
            with st.spinner("正在检查所有持仓..."):
                status_area = st.empty()
                results = run_portfolio_check(status_area)
                status_area.empty()

            # ── 股票盈亏表 ──
            if results["stocks"]:
                st.subheader("📈 股票持仓")
                rows = []
                for r in results["stocks"]:
                    if "error" in r:
                        rows.append([r.get("code", "?"), r.get("name", "?"), "N/A", "N/A", "N/A", "N/A", "获取失败"])
                    else:
                        pnl_color = "🟢" if r["pnl"] >= 0 else "🔴"
                        rows.append([
                            r["code"], r["name"],
                            f"¥{r['buy_price']:.2f}", f"¥{r['current_price']:.2f}",
                            f"{r['shares']}股", f"¥{r['market_value']:,.0f}",
                            f"{pnl_color} ¥{r['pnl']:+,.0f} ({r['pnl_pct']:+.1f}%)",
                        ])
                header = ["代码", "名称", "买入价", "现价", "数量", "市值", "盈亏"]
                stock_rows = [{h: v for h, v in zip(header, row)} for row in rows]
                st.dataframe(stock_rows, use_container_width=True, hide_index=True)

                # 汇总
                total_cost = sum(r.get("buy_price", 0) * r.get("shares", 0)
                                 for r in results["stocks"] if "error" not in r)
                total_value = sum(r.get("market_value", 0)
                                  for r in results["stocks"] if "error" not in r)
                total_pnl = total_value - total_cost
                total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
                pnl_sign = "+" if total_pnl >= 0 else ""
                st.metric(
                    "股票总盈亏",
                    f"{pnl_sign}¥{total_pnl:,.0f}",
                    f"{pnl_sign}{total_pnl_pct:.1f}%"
                )

            # ── 基金盈亏表 ──
            if results["funds"]:
                st.subheader("📊 基金持仓")
                rows = []
                for r in results["funds"]:
                    if "error" in r:
                        rows.append([r.get("code", "?"), r.get("name", "?"), "N/A", "N/A", "N/A", "N/A", "获取失败"])
                    else:
                        pnl_color = "🟢" if r["pnl"] >= 0 else "🔴"
                        rows.append([
                            r["code"], r["name"],
                            f"¥{r['buy_nav']:.4f}", f"¥{r['current_nav']:.4f}",
                            f"¥{r['amount']:,.0f}", f"¥{r['market_value']:,.0f}",
                            f"{pnl_color} ¥{r['pnl']:+,.0f} ({r['pnl_pct']:+.1f}%)",
                        ])
                header = ["代码", "名称", "买入净值", "现净值", "投入", "市值", "盈亏"]
                # Build table row by row
                display_rows = []
                for row in rows:
                    display_rows.append({h: v for h, v in zip(header, row)})
                st.dataframe(display_rows, use_container_width=True, hide_index=True)

                total_cost = sum(r.get("amount", 0) for r in results["funds"] if "error" not in r)
                total_value = sum(r.get("market_value", 0) for r in results["funds"] if "error" not in r)
                total_pnl = total_value - total_cost
                total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
                pnl_sign = "+" if total_pnl >= 0 else ""
                st.metric(
                    "基金总盈亏",
                    f"{pnl_sign}¥{total_pnl:,.0f}",
                    f"{pnl_sign}{total_pnl_pct:.1f}%"
                )

            # ── 告警 ──
            if results["alerts"]:
                st.subheader("🚨 告警提醒")
                for alert in results["alerts"]:
                    st.warning(alert)
            elif monitor_btn:
                st.success("✅ 所有持仓正常，无需告警")

# ── Tab 3: 注册推送 ───────────────────────────

with tab_register:
    st.subheader("📝 注册定时推送")

    st.markdown("""
    配置你的持仓和微信推送，每个交易日 **10:00** 和 **14:30** 自动收到 A 股分析报告。

    **只需要两步：**
    """)

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### ① 获取微信推送 key")
        st.markdown("打开 [sct.ftqq.com](https://sct.ftqq.com) 微信扫码，复制 **SendKey**")
        reg_sendkey = st.text_input("粘贴 SendKey", placeholder="SCTxxxxxxxx", key="reg_sendkey")

    with col_b:
        st.markdown("### ② 添加持仓")
        reg_name = st.text_input("你的名字（用于报告抬头）", placeholder="如：小王", key="reg_name")

        reg_ftype = st.selectbox("类型", ["基金", "股票"], key="reg_ftype")
        reg_code = st.text_input("代码（6位）", placeholder="如 161725", key="reg_code")
        reg_alert = st.number_input("单日涨跌提醒阈值（%）", min_value=1, max_value=20, value=3, key="reg_alert")

        if "reg_holdings" not in st.session_state:
            st.session_state.reg_holdings = []

        if st.button("➕ 添加", key="reg_add"):
            if reg_code and len(reg_code) == 6:
                # 自动获取名称
                auto_name = reg_code
                if reg_ftype == "基金":
                    v = api_fund_valuation(reg_code)
                    auto_name = v["name"] if v else reg_code
                else:
                    q = api_stock_quote(reg_code)
                    auto_name = q["name"] if q else reg_code

                st.session_state.reg_holdings.append({
                    "code": reg_code, "name": auto_name,
                    "type": reg_ftype, "alert_change_pct": reg_alert,
                })
                st.rerun()
            else:
                st.error("请输入6位代码")

        if st.session_state.reg_holdings:
            st.caption(f"已添加 {len(st.session_state.reg_holdings)} 项:")
            for i, h in enumerate(st.session_state.reg_holdings):
                st.text(f"  {h['type']}: {h['name']}({h['code']}) | 提醒阈值: {h['alert_change_pct']}%")
            if st.button("清空重填", key="reg_clear"):
                st.session_state.reg_holdings = []
                st.rerun()

    st.divider()

    # 提交到 Google Sheets
    if reg_name and st.session_state.reg_holdings:
        st.markdown("### ③ 提交")
        if st.button("🚀 提交，明天起收到推送", type="primary", key="reg_submit"):
            funds = []
            stocks = []
            for h in st.session_state.reg_holdings:
                item = {"code": h["code"], "name": h["name"], "alert_change_pct": h["alert_change_pct"]}
                if h["type"] == "基金":
                    item["alert_nav_below"] = 0
                    funds.append(item)
                else:
                    item["alert_below"] = 0
                    stocks.append(item)

            try:
                import sheets_db
                sheets_db.add_user_holdings(reg_name, funds, stocks)
                st.success(f"✅ 已保存！明天起 {reg_name} 就会准时收到推送 🎉")
                st.balloons()
            except Exception as e:
                st.error(f"提交失败: {e}")
                st.info("请截屏发给管理员手动添加")

# ═══════════════════════════════════════════════
# 底部
# ═══════════════════════════════════════════════

st.divider()
st.caption(
    "⚠️ 以上分析基于公开数据，不构成投资建议。股市有风险，入市需谨慎。"
    " | 数据来源：东方财富 / 天天基金 | 模型：DeepSeek V4"
)
