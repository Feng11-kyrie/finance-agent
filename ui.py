"""统一页面视觉：配色、字体、间距、卡片与页头。

只做展示层，不参与业务逻辑；所有样式都通过一段 CSS 注入。
"""
from __future__ import annotations

import streamlit as st

CSS = """
:root {
  --ink: #0F172A;
  --muted: #64748B;
  --line: #E6EBF2;
  --accent: #2563EB;
  --soft: #F6F8FB;
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
               "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
  color: var(--ink);
}

.stApp { background: #FFFFFF; }

/* 隐藏 Streamlit 默认菜单/工具栏/彩色装饰条 */
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { background: transparent; }
[data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenu"],
#MainMenu, footer,
[data-testid="stDecoration"] { display: none !important; }

/* 移动端保留侧边栏展开按钮 */
[data-testid="stExpandSidebarButton"] { color: #0F172A; }

.block-container {
  max-width: 1180px;
  padding-top: 2.4rem;
  padding-bottom: 3rem;
}

/* 侧边栏 */
[data-testid="stSidebar"] {
  background: #F8FAFC;
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
[data-testid="stSidebar"] hr { margin: 1rem 0; border-color: var(--line); }

.side-brand {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -.01em;
  color: #0B1220;
  margin: 0 0 1.2rem;
}
.side-brand span { color: var(--accent); }

.step-title {
  font-size: 15px;
  font-weight: 650;
  color: #0B1220;
  margin: .1rem 0 .6rem;
}

.side-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .14em;
  color: var(--muted);
  margin: 0 0 .55rem 0;
}

/* 页头 */
.hero {
  padding-bottom: 1.1rem;
  border-bottom: 1px solid #EEF2F7;
  margin-bottom: 1.1rem;
}
.hero .eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .18em;
  color: var(--accent);
}
.hero h1 {
  font-size: 2.05rem;
  line-height: 1.18;
  font-weight: 700;
  letter-spacing: -.035em;
  margin: .4rem 0 .45rem;
  color: #0B1220;
}
.hero p { margin: 0; color: var(--muted); font-size: .95rem; }
.hero .chips { display: flex; flex-wrap: wrap; gap: .45rem; margin-top: .85rem; }
.hero .chips span {
  font-size: 12px;
  color: #334155;
  background: #F1F5F9;
  border: 1px solid var(--line);
  padding: 3px 10px;
  border-radius: 999px;
}

/* 标签页 */
[data-baseweb="tab-list"] { gap: 1.5rem; border-bottom: 1px solid var(--line); }
button[data-baseweb="tab"] {
  padding: .65rem 0;
  color: var(--muted);
  font-size: 14px;
  font-weight: 500;
}
button[data-baseweb="tab"][aria-selected="true"] { color: #0B1220; font-weight: 650; }
[data-baseweb="tab-highlight"] { background: var(--accent); height: 2px; }
[data-baseweb="tab-border"] { display: none; }

/* 按钮 */
.stButton > button, .stDownloadButton > button,
[data-testid="stFormSubmitButton"] button {
  border-radius: 10px;
  border: 1px solid #DCE3EC;
  font-weight: 500;
  transition: background .15s ease, border-color .15s ease, box-shadow .15s ease;
}
[data-testid="stBaseButton-primary"] {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  color: #fff !important;
  box-shadow: 0 1px 2px rgba(37, 99, 235, .18);
}
[data-testid="stBaseButton-primary"]:hover {
  background: #1D4ED8 !important;
  border-color: #1D4ED8 !important;
}

/* 输入框 */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
  border-radius: 10px !important;
  border-color: #DCE3EC !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, .10);
}

/* 卡片 / 折叠面板 / 指标 / 表格 */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 14px;
  border-color: var(--line);
  box-shadow: 0 1px 2px rgba(15, 23, 42, .03);
}
[data-testid="stExpander"] {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
}
[data-testid="stExpander"] summary { font-weight: 500; color: #334155; }
[data-testid="stMetric"] {
  background: var(--soft);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: .8rem 1rem;
}
[data-testid="stMetricValue"] { font-size: 1.35rem; }
[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
[data-testid="stAlert"] { border-radius: 12px; }

/* 文件上传控件的中文化（隐藏 Streamlit 内置英文） */
[data-testid="stFileUploaderDropzoneInstructions"] div > span:first-child {
  font-size: 0;
}
[data-testid="stFileUploaderDropzoneInstructions"] div > span:first-child::after {
  content: "拖拽 CSV / XLSX 文件到此处";
  font-size: 14px;
  color: #334155;
}
[data-testid="stFileUploaderDropzoneInstructions"] div > span:last-child {
  display: none;
}
[data-testid="stFileUploaderDropzone"] button { font-size: 0 !important; }
[data-testid="stFileUploaderDropzone"] button::after {
  content: "浏览文件";
  font-size: 14px;
}

/* 盈亏概览条（A 股习惯：红涨绿跌） */
.pnl-line {
  display: flex;
  align-items: baseline;
  gap: .75rem;
  width: fit-content;
  min-width: 300px;
  max-width: 100%;
  margin-top: .8rem;
  padding: .7rem .95rem;
  background: var(--soft);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.pnl-line span { color: var(--muted); font-size: 13px; }
.pnl-line strong { font-size: 1.3rem; letter-spacing: -.02em; }
.pnl-line em { font-style: normal; font-size: 13px; font-weight: 600; }
.gain { color: #DC2626; }
.loss { color: #16A34A; }
.flat { color: #475569; }

/* 空状态与页脚 */
.empty-state {
  margin-top: 1rem;
  padding: 2.2rem 1.5rem;
  border: 1px dashed #DCE3EC;
  border-radius: 14px;
  background: #FBFDFF;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
}
.empty-state strong {
  display: block;
  color: var(--ink);
  font-size: 15px;
  margin-bottom: .35rem;
}
@media (max-width: 640px) {
  .block-container { padding: 1.2rem 1rem 2rem; }
  .hero h1 { font-size: 1.7rem; }
  .hero p { font-size: .88rem; }
  .hero .chips span { font-size: 11px; }
  [data-baseweb="tab-list"] { gap: .85rem; }
  button[data-baseweb="tab"] { font-size: 13px; padding: .55rem 0; }
  .pnl-line { width: 100%; min-width: 0; }
}

.app-footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid #EEF2F7;
  color: #94A3B8;
  font-size: 12px;
  line-height: 1.8;
}
"""

HERO = """
<div class="hero">
  <div class="eyebrow">AI FINANCE RESEARCH</div>
  <h1>金融研报 Agent</h1>
  <p>覆盖 A 股 5000+ 与公募基金 10000+，每个交易日 10:00 / 14:30 自动生成研报。</p>
  <div class="chips">
    <span>Agent 自主调用工具</span>
    <span>7 个数据工具</span>
    <span>微信双通道推送</span>
  </div>
</div>
"""


def inject_css() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def hero() -> None:
    st.markdown(HERO, unsafe_allow_html=True)


def step_title(text: str) -> None:
    st.markdown(f'<div class="step-title">{text}</div>', unsafe_allow_html=True)


def sidebar_brand() -> None:
    st.markdown(
        '<div class="side-brand">金融研报 <span>Agent</span></div>',
        unsafe_allow_html=True,
    )


def sidebar_title(text: str) -> None:
    st.markdown(f'<div class="side-title">{text}</div>', unsafe_allow_html=True)


def footer(text: str) -> None:
    st.markdown(f'<div class="app-footer">{text}</div>', unsafe_allow_html=True)
