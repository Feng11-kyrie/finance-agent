"""
金融研报 Agent - Streamlit 网页版（真实数据）
覆盖：全部 A 股 + 支付宝/天天基金所有公募基金

运行方式: python3 -m streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import holdings_import
import sheets_db
import ui
import vision_import
from agent import get_api_key, run_agent
from data_api import api_stock_quote, api_fund_valuation

# ═══════════════════════════════════════════════
# 页面配置
# ═══════════════════════════════════════════════

st.set_page_config(
    page_title="金融研报 Agent",
    page_icon="📊",
    layout="wide",
)

ui.inject_css()
ui.hero()

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


def render_pnl_summary(label: str, pnl: float, pct: float) -> None:
    """紧凑的盈亏条：A 股习惯红涨绿跌。"""
    cls = "gain" if pnl > 0 else ("loss" if pnl < 0 else "flat")
    sign = "+" if pnl > 0 else ""
    st.markdown(
        f'<div class="pnl-line"><span>{label}</span>'
        f'<strong class="{cls}">{sign}¥{pnl:,.0f}</strong>'
        f'<em class="{cls}">{pct:+.1f}%</em></div>',
        unsafe_allow_html=True,
    )


def _pnl_style(value) -> str:
    text = str(value)
    if "¥+0" in text or "¥0" in text:
        return "color:#475569;font-weight:600"
    if "¥+" in text:
        return "color:#DC2626;font-weight:600"
    if "¥-" in text:
        return "color:#16A34A;font-weight:600"
    return ""


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
                    f"{pnl['name']}({pnl['code']}) 浮亏 {abs(pnl['pnl_pct']):.1f}%，"
                    f"当前价 ¥{pnl['current_price']:.2f}，建议关注"
                )
            elif pnl["pnl_pct"] >= 10:
                results["alerts"].append(
                    f"{pnl['name']}({pnl['code']}) 浮盈 {pnl['pnl_pct']:.1f}%，"
                    f"当前价 ¥{pnl['current_price']:.2f}，可考虑止盈"
                )
            if abs(pnl["change_today"]) >= 5:
                direction = "大涨" if pnl["change_today"] > 0 else "大跌"
                results["alerts"].append(
                    f"{pnl['name']}({pnl['code']}) 今日{direction} {pnl['change_today']:+.1f}%"
                )

    for h in holdings["funds"]:
        status_container.text(f"检查基金: {h['name']}({h['code']})...")
        val = api_fund_valuation(h["code"])
        pnl = compute_fund_pnl(h, val)
        results["funds"].append(pnl)
        if "error" not in pnl:
            if pnl["pnl_pct"] <= -5:
                results["alerts"].append(
                    f"{pnl['name']}({pnl['code']}) 浮亏 {abs(pnl['pnl_pct']):.1f}%，建议关注"
                )

    return results


# ═══════════════════════════════════════════════
# 页面初始化
# ═══════════════════════════════════════════════

init_holdings()

# ── 侧边栏 ─────────────────────────────────────

with st.sidebar:
    ui.sidebar_brand()
    ui.sidebar_title("快速查询")

    with st.expander("热门股票", expanded=False):
        stocks = {
            "贵州茅台 (600519)": "帮我全面分析一下贵州茅台",
            "宁德时代 (300750)": "宁德时代最近走势怎么样，适合入手吗？",
            "比亚迪 (002594)": "比亚迪目前的行情和技术面如何？",
            "中国平安 (601318)": "中国平安现在的估值水平怎么样？",
        }
        for label, question in stocks.items():
            if st.button(label, use_container_width=True, key=f"stock_{label[:10]}"):
                st.session_state.question = question

    with st.expander("热门基金", expanded=False):
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
    ui.sidebar_title("我的持仓")

    tab1, tab2 = st.tabs(["添加", "列表"])

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

        if st.button("添加到持仓", use_container_width=True, type="primary"):
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
            st.caption("暂无持仓，先在「添加」里录入或到「导入持仓」上传文件")
        else:
            st.caption(f"{total_stocks} 支股票 · {total_funds} 支基金")

            for i, h in enumerate(holdings_data["stocks"]):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{h['name']}** `{h['code']}`")
                    st.caption(f"买入 ¥{h['buy_price']} × {h['shares']} 股")
                with col2:
                    if st.button("✕", key=f"del_s_{i}"):
                        remove_holding("stocks", i)
                        st.rerun()

            for i, h in enumerate(holdings_data["funds"]):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{h['name']}** `{h['code']}`")
                    st.caption(f"买入净值 ¥{h['buy_nav']} · 金额 ¥{h['amount']}")
                with col2:
                    if st.button("✕", key=f"del_f_{i}"):
                        remove_holding("funds", i)
                        st.rerun()

            if st.button("清空全部", use_container_width=True):
                st.session_state.holdings = {"stocks": [], "funds": []}
                st.rerun()

    st.divider()
    st.caption("A 股 5000+ · 公募基金 10000+")
    st.caption("数据源：东方财富 / 天天基金")

# ═══════════════════════════════════════════════
# 主区域
# ═══════════════════════════════════════════════

tab_analyze, tab_import, tab_monitor, tab_register = st.tabs([
    "智能分析", "导入持仓", "持仓监控", "定时推送",
])

# ── Tab 1: 智能分析 ───────────────────────────

with tab_analyze:
    pending = st.session_state.get("pending_question")
    if pending:
        del st.session_state["pending_question"]
        st.session_state.question = pending

    st.caption("用自然语言提问，Agent 会自己决定调用哪些工具、按什么顺序调用。")

    with st.container(border=True):
        col1, col2, col3 = st.columns(
            [3.4, 1.1, 1.1], vertical_alignment="bottom"
        )
        with col1:
            user_input = st.text_input(
                "输入你的问题",
                placeholder="输入股票 / 基金名称或 6 位代码，如：宁德时代、000218",
                key="question",
                label_visibility="collapsed",
            )
        with col2:
            fast_mode = st.toggle(
                "快速模式", value=True,
                help="快速模式响应更快；关闭后分析更详细，但会稍慢",
            )
        with col3:
            analyze_btn = st.button(
                "开始分析", type="primary", use_container_width=True
            )

    if analyze_btn and user_input:
        with st.spinner("Agent 正在分析..."):
            status_area = st.empty()
            result = run_agent(user_input, status_area, fast_mode=fast_mode)
            status_area.empty()

        st.markdown("#### 分析结果")
        with st.container(border=True):
            st.markdown(result)
    else:
        st.markdown(
            '<div class="empty-state"><strong>从一只股票或基金开始</strong>'
            '输入名称或 6 位代码，Agent 会自动搜索标的、拉取行情与 K 线，再生成分析。</div>',
            unsafe_allow_html=True,
        )
        st.caption("试试这些")
        examples = [
            ("分析宁德时代", "帮我全面分析一下宁德时代"),
            ("分析贵州茅台", "帮我全面分析一下贵州茅台"),
            ("看看 000218", "帮我看看国泰黄金ETF联接A 000218 的净值走势"),
        ]
        with st.container(horizontal=True, gap="small"):
            for label, question in examples:
                if st.button(label, key=f"example_{label}"):
                    st.session_state.pending_question = question
                    st.rerun()

# ── Tab 2: 导入持仓 ───────────────────────────

with tab_import:
    st.caption("上传持仓截图由 AI 识别，或导入 CSV / Excel；核对后可直接保存为每日推送。")

    flash = st.session_state.get("import_flash", "")
    if flash:
        del st.session_state["import_flash"]
        st.success(flash)

    mode = st.radio(
        "导入方式", ["截图识别", "CSV / Excel"],
        horizontal=True, key="import_mode",
    )

    if mode == "截图识别":
        with st.container(border=True):
            col_shot, col_opt = st.columns([2, 1])
            with col_shot:
                shot = st.file_uploader(
                    "上传持仓截图",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="vision_file",
                    help="支持支付宝、天天基金、腾讯理财通、雪球的持有/持仓页面截图",
                )
            with col_opt:
                platform = st.selectbox(
                    "截图来源",
                    ["支付宝", "天天基金", "腾讯理财通", "雪球", "其他"],
                    key="vision_platform",
                )
                st.caption("截图会发送给 DeepSeek 视觉模型识别。")

            if shot is not None:
                st.image(shot, width=360)
                if st.button("识别持仓", type="primary", key="vision_run"):
                    with st.spinner("正在识别截图..."):
                        try:
                            rows, warnings, _ = vision_import.recognize(
                                shot.getvalue(), shot.name, platform,
                                get_api_key(),
                            )
                        except Exception as e:
                            st.error(f"识别失败：{e}")
                        else:
                            rows, enrich_warnings = vision_import.enrich_rows(rows)
                            warnings = warnings + enrich_warnings
                            if rows and all(r.get("code") for r in rows):
                                # 代码已按名称补全，去掉模型“未显示代码”的提示
                                warnings = [w for w in warnings if "代码" not in str(w)]
                            st.session_state["vision_rows"] = rows
                            st.session_state["vision_warnings"] = warnings
                            st.session_state["vision_nonce"] = (
                                st.session_state.get("vision_nonce", 0) + 1
                            )

        rows = st.session_state.get("vision_rows", [])
        warnings = st.session_state.get("vision_warnings", [])
        if rows:
            st.success(f"识别到 {len(rows)} 条持仓，请核对后导入")
            nonce = st.session_state.get("vision_nonce", 0)
            edited = st.data_editor(
                pd.DataFrame(vision_import.rows_for_editor(rows)),
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key=f"vision_editor_{nonce}",
                column_config={
                    "类型": st.column_config.SelectboxColumn(
                        "类型", options=["基金", "股票"], required=True,
                    ),
                    "代码": st.column_config.TextColumn("代码", max_chars=6),
                    "名称": st.column_config.TextColumn("名称"),
                    "买入价/净值": st.column_config.TextColumn("买入价/净值"),
                    "份额": st.column_config.TextColumn("份额"),
                    "金额": st.column_config.TextColumn("金额"),
                    "当前市值": st.column_config.TextColumn("当前市值"),
                    "收益": st.column_config.TextColumn("收益"),
                },
            )
            notes = sorted({
                str(row.get("note", "")).strip()
                for row in rows if str(row.get("note", "")).strip()
            })
            if notes:
                st.caption("识别说明：" + "；".join(notes))

            if st.button("导入识别结果", type="primary", key="vision_apply"):
                new_rows, row_errors = vision_import.editor_to_rows(edited)
                if new_rows:
                    with st.spinner("正在补全成本..."):
                        new_rows, enrich_errors = vision_import.enrich_rows(new_rows)
                    clean_rows = []
                    for row in new_rows:
                        if (
                            row.get("type") == "stock"
                            and row.get("buy_price") and row.get("shares")
                        ):
                            clean_rows.append({
                                "type": "stock", "code": row["code"],
                                "name": row["name"], "buy_price": row["buy_price"],
                                "shares": row["shares"],
                            })
                        elif (
                            row.get("type") == "fund"
                            and row.get("buy_nav") and row.get("amount")
                        ):
                            clean_rows.append({
                                "type": "fund", "code": row["code"],
                                "name": row["name"], "buy_nav": row["buy_nav"],
                                "amount": row["amount"],
                            })
                    if clean_rows:
                        merged, added, updated = holdings_import.merge_holdings(
                            st.session_state.holdings, clean_rows
                        )
                        st.session_state.holdings = merged
                        st.session_state["import_flash"] = (
                            f"已导入：新增 {added} 条，更新 {updated} 条"
                        )
                        st.session_state["vision_rows"] = []
                        st.session_state["vision_warnings"] = []
                        st.rerun()
                    else:
                        st.error("没有可导入的有效行，请检查代码、价格和金额")
                    for err in enrich_errors[:5]:
                        st.warning(err)
                else:
                    st.error("没有可导入的有效行，请检查代码、价格和金额")
                for err in row_errors[:5]:
                    st.warning(err)

        for warning in warnings[:8]:
            st.warning(warning)
    else:
        with st.container(border=True):
            col_up, col_side = st.columns([3, 2])
            with col_up:
                uploaded = st.file_uploader(
                    "上传持仓文件",
                    type=["csv", "xlsx"],
                    key="import_file",
                    help="支持券商、天天基金导出的 CSV/Excel，或下载右侧模板填写",
                )
            with col_side:
                st.download_button(
                    "下载 CSV 模板",
                    holdings_import.CSV_TEMPLATE.encode("utf-8-sig"),
                    "holdings_template.csv",
                    "text/csv",
                    use_container_width=True,
                )
                type_mode = st.selectbox(
                    "类型识别", ["自动识别", "全部基金", "全部股票"],
                    key="import_type_mode",
                )

        rows = []
        errors = []
        mapping = {}
        if uploaded is not None:
            try:
                df = holdings_import.read_table(uploaded.getvalue(), uploaded.name)
                rows, errors, mapping = holdings_import.parse_holdings(
                    df, {"自动识别": "auto", "全部基金": "fund", "全部股票": "stock"}[type_mode]
                )
            except Exception as e:
                st.error(f"读取失败：{e}")

            if mapping:
                with st.expander("识别到的列", expanded=False):
                    st.json(mapping)

            if rows:
                st.success(f"识别到 {len(rows)} 条有效持仓")
                st.dataframe(
                    pd.DataFrame(holdings_import.display_rows(rows)),
                    use_container_width=True,
                    hide_index=True,
                )
            for err in errors[:8]:
                st.warning(err)
            if len(errors) > 8:
                st.caption(f"另有 {len(errors) - 8} 条未通过校验，导入时会跳过。")

            if rows and st.button("导入到当前持仓", type="primary", key="import_apply"):
                new_holdings, added, updated = holdings_import.merge_holdings(
                    st.session_state.holdings, rows
                )
                st.session_state.holdings = new_holdings
                st.session_state["import_flash"] = f"已导入：新增 {added} 条，更新 {updated} 条"
                st.rerun()

    st.divider()
    st.subheader("保存为每日推送")
    st.caption("保存到 Google Sheets 后，每个交易日 10:00 / 14:30 会自动生成并推送报告。")

    current = st.session_state.holdings
    total = len(current["stocks"]) + len(current["funds"])
    if not total:
        st.info("先导入或添加持仓，再保存到 Google Sheets。")
    else:
        st.caption(
            f"将保存当前 {total} 条持仓"
            f"（{len(current['stocks'])} 股票 / {len(current['funds'])} 基金）"
        )
        c1, c2 = st.columns(2)
        with c1:
            save_name = st.text_input("姓名（报告抬头）", key="import_save_name")
        with c2:
            save_sendkey = st.text_input(
                "Server酱 SendKey（可选）",
                type="password",
                key="import_save_sendkey",
                help="不填则使用服务器环境变量里的 SERVERCHAN_SENDKEY",
            )
        if st.button("保存到 Google Sheets", type="primary", key="import_save"):
            if not save_name.strip():
                st.error("请填写姓名")
            else:
                try:
                    funds, stocks = holdings_import.to_sheet_payload(current)
                    sheets_db.add_user_holdings(
                        save_name.strip(), funds, stocks,
                        sendkey=save_sendkey.strip(),
                    )
                    st.success(
                        f"已保存 {len(funds) + len(stocks)} 条持仓；"
                        "之后每个交易日会自动生成报告。"
                    )
                except Exception as e:
                    st.error(f"保存失败：{e}")
                    st.info("请确认 .env / Streamlit Secrets 中已配置 GCP_SERVICE_ACCOUNT 和 GOOGLE_SHEET_ID")

# ── Tab 3: 持仓监控 ───────────────────────────

with tab_monitor:
    st.caption("实时计算持仓盈亏，并对浮亏、浮盈和日内异动给出提醒。")

    holdings_data = st.session_state.holdings
    has_holdings = len(holdings_data["stocks"]) > 0 or len(holdings_data["funds"]) > 0

    if not has_holdings:
        st.info("先在左侧「我的持仓」添加，或到「导入持仓」上传文件，然后回到这里开始监控。")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            monitor_btn = st.button("开始监控", type="primary", use_container_width=True)
        with col2:
            st.caption(f"当前监控 {len(holdings_data['stocks'])} 支股票 + {len(holdings_data['funds'])} 支基金")

        if monitor_btn:
            with st.spinner("正在检查所有持仓..."):
                status_area = st.empty()
                results = run_portfolio_check(status_area)
                status_area.empty()

            # ── 股票盈亏表 ──
            if results["stocks"]:
                with st.container(border=True):
                    st.markdown("#### 股票持仓")
                    rows = []
                    for r in results["stocks"]:
                        if "error" in r:
                            rows.append([r.get("code", "?"), r.get("name", "?"), "N/A", "N/A", "N/A", "N/A", "获取失败"])
                        else:
                            rows.append([
                                r["code"], r["name"],
                                f"¥{r['buy_price']:.2f}", f"¥{r['current_price']:.2f}",
                                f"{r['shares']}股", f"¥{r['market_value']:,.0f}",
                                f"¥{r['pnl']:+,.0f} ({r['pnl_pct']:+.1f}%)",
                            ])
                    header = ["代码", "名称", "买入价", "现价", "数量", "市值", "盈亏"]
                    stock_df = pd.DataFrame(rows, columns=header)
                    st.dataframe(
                        stock_df.style.map(_pnl_style, subset=["盈亏"]),
                        use_container_width=True, hide_index=True,
                    )

                    total_cost = sum(r.get("buy_price", 0) * r.get("shares", 0)
                                     for r in results["stocks"] if "error" not in r)
                    total_value = sum(r.get("market_value", 0)
                                      for r in results["stocks"] if "error" not in r)
                    total_pnl = total_value - total_cost
                    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
                    render_pnl_summary("股票总盈亏", total_pnl, total_pnl_pct)

            # ── 基金盈亏表 ──
            if results["funds"]:
                with st.container(border=True):
                    st.markdown("#### 基金持仓")
                    rows = []
                    for r in results["funds"]:
                        if "error" in r:
                            rows.append([r.get("code", "?"), r.get("name", "?"), "N/A", "N/A", "N/A", "N/A", "获取失败"])
                        else:
                            rows.append([
                                r["code"], r["name"],
                                f"¥{r['buy_nav']:.4f}", f"¥{r['current_nav']:.4f}",
                                f"¥{r['amount']:,.0f}", f"¥{r['market_value']:,.0f}",
                                f"¥{r['pnl']:+,.0f} ({r['pnl_pct']:+.1f}%)",
                            ])
                    header = ["代码", "名称", "买入净值", "现净值", "投入", "市值", "盈亏"]
                    fund_df = pd.DataFrame(rows, columns=header)
                    st.dataframe(
                        fund_df.style.map(_pnl_style, subset=["盈亏"]),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption("无实时估值时按最近净值计算，涨跌幅为最近净值日数据。")

                    total_cost = sum(r.get("amount", 0) for r in results["funds"] if "error" not in r)
                    total_value = sum(r.get("market_value", 0) for r in results["funds"] if "error" not in r)
                    total_pnl = total_value - total_cost
                    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
                    render_pnl_summary("基金总盈亏", total_pnl, total_pnl_pct)

            # ── 告警 ──
            if results["alerts"]:
                st.markdown("#### 告警提醒")
                for alert in results["alerts"]:
                    st.warning(alert)
            elif monitor_btn:
                st.success("所有持仓正常，无需告警")

# ── Tab 4: 注册推送 ───────────────────────────

with tab_register:
    st.markdown("""
    配置你的持仓和微信推送，每个交易日 **10:00** 和 **14:30** 自动收到 A 股分析报告。

    **三步完成：**
    """)

    col_a, col_b = st.columns(2)

    with col_a:
        ui.step_title("① 获取微信推送 key")
        st.markdown(
            "1. 打开 [sct.ftqq.com](https://sct.ftqq.com)，微信扫码登录\n"
            "2. 复制页面上的 **SendKey**\n"
            "3. 粘贴到下方"
        )
        reg_sendkey = st.text_input("粘贴 SendKey", placeholder="SCTxxxxxxxx", key="reg_sendkey")
        st.caption("只用于给你本人推送，可随时在 Server酱后台重置。")

    with col_b:
        ui.step_title("② 添加持仓")
        reg_name = st.text_input("你的名字（用于报告抬头）", placeholder="如：小王", key="reg_name")

        reg_ftype = st.selectbox("类型", ["基金", "股票"], key="reg_ftype")
        reg_code = st.text_input("代码（6位）", placeholder="如 161725", key="reg_code")
        reg_alert = st.number_input("单日涨跌提醒阈值（%）", min_value=1, max_value=20, value=3, key="reg_alert")

        if "reg_holdings" not in st.session_state:
            st.session_state.reg_holdings = []

        if st.button("添加", key="reg_add"):
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
        ui.step_title("③ 提交")
        if st.button("提交并保存", type="primary", key="reg_submit"):
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
                sheets_db.add_user_holdings(
                    reg_name.strip(), funds, stocks, sendkey=reg_sendkey.strip()
                )
                st.success(f"已保存，明天起 {reg_name} 会准时收到推送。")
            except Exception as e:
                st.error(f"提交失败: {e}")
                st.info("请截屏发给管理员手动添加")

# ═══════════════════════════════════════════════
# 底部
# ═══════════════════════════════════════════════

ui.footer(
    "以上分析基于公开数据，不构成投资建议。股市有风险，入市需谨慎。"
    "<br>数据来源：东方财富 / 天天基金"
)
