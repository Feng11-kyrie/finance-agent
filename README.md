# 📊 金融研报 Agent · AI Finance Agent

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.45+-red.svg)](https://streamlit.io)
[![DeepSeek](https://img.shields.io/badge/AI-DeepSeek%20V4-green.svg)](https://deepseek.com)
[![Schedule](https://img.shields.io/badge/schedule-Local%20Cron-2088FF.svg)](#-architecture)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF.svg)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

🚀 **在线体验（网页版）：** https://finance-agent-pabcy4yeagmhvj25gaxz3z.streamlit.app/

**English** | [中文](#中文)

> An AI agent that autonomously analyzes 5,000+ Chinese A-shares and 10,000+ mutual funds, generating daily research reports pushed to WeChat — fully automated, zero operating cost.

## 🎬 Demo

<!-- TODO: 上传录屏到 YouTube/B站后替换下面链接 -->
> *Demo video coming soon*

**🌐 无需安装，直接打开：** https://finance-agent-pabcy4yeagmhvj25gaxz3z.streamlit.app/

**Try it yourself:**
```bash
pip install -r requirements.txt
streamlit run app.py
```

| Streamlit Web UI | Holdings monitor |
|:--:|:--:|
| ![Streamlit UI](docs/ui-analysis.png) | ![Holdings monitor](docs/ui-monitor.png) |

---

## 🧠 Core Feature: AI Agent with Autonomous Tool-Use

Unlike a regular chatbot, this system implements a **hand-written Agent Loop** (~50 lines) that autonomously decides which tools to call:

```
User: "分析宁德时代"
  → Agent calls search_stock("宁德") → gets 300750
  → Agent calls get_stock_quote("300750") → gets real-time price
  → Agent calls get_stock_kline("300750") → gets 30-day trend
  → Agent synthesizes all data → generates analysis report
```

**7 Built-in Tools**: search_stock · get_stock_quote · get_stock_kline · search_fund · get_fund_valuation · get_fund_nav_history · get_fund_info

**Holdings import**: upload a CSV/XLSX exported from your broker, preview parsed rows, import them into the session, and save the list for the daily push.

---

## 🏗 Architecture

```
User Registers (Streamlit)
       │
       ▼
Google Sheets (user holdings DB)
       │
       ▼  local crontab: 10:00 & 14:30 BJT Mon-Fri
Python Report Generator ─→ DeepSeek V4 AI
                               │
                               ▼
                 ┌─ cc-connect → WeChat Bot (PC on)
                 └─ Server酱 ──→ WeChat OA (fallback)
```

> GitHub Actions 工作流仍保留，但只用于手动触发，避免和本机 cron 重复推送。
>
> 多用户时可在 Google Sheets 增加可选的 `cc_target` 列（本地 JSON 同理）；不配置则走 Server酱，避免把不同用户的报告发进同一个微信会话。

---

## 🛠 Tech Stack

| Layer | Tech | Why |
|------|------|-----|
| AI | DeepSeek V4 via Anthropic SDK | Hand-written Agent Loop, 7 tools |
| Data | Sina / EastMoney / TianTian Fund APIs | Free, covers all A-shares + funds |
| Storage | Google Sheets + gspread | $0, built-in Web UI, fallback to local JSON |
| Schedule | Local crontab (GitHub Actions as manual backup) | Runs on the machine that owns the WeChat bot |
| Push | cc-connect (iLink Bot) + Server酱 | Dual-channel with auto-failover |
| Frontend | Streamlit + custom theme | Python-native, zero frontend code |
| Cost | **¥0 / month** | Entirely free tier |

---

## 📁 Project Structure

```
finance-agent/
├── app.py                  # Streamlit web app (analysis + registration)
├── agent.py                # Agent loop + 7 tool definitions
├── holdings_import.py      # CSV/XLSX holdings parser + validation
├── data_api.py             # Sina / EastMoney / TianTian data layer
├── report_generator.py     # Report engine (local cron entry point)
├── sheets_db.py            # Google Sheets data layer (with local fallback)
├── config_loader.py        # Central model config loader
├── ui.py                   # Shared visual theme (CSS, hero, footer)
├── .streamlit/config.toml  # Streamlit theme colors
├── config.json             # Model names (fast / pro / report)
├── run_local.sh            # Cron wrapper (loads .env, starts cc-connect)
├── tests/                  # Unit tests (trading day, parsing, retries)
├── .github/workflows/      # Manual report trigger + CI tests
└── README.md
```

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Environment variables (for cron mode):
```bash
export ANTHROPIC_API_KEY=sk-xxx
export SERVERCHAN_SENDKEY=SCTxxx
export GOOGLE_SHEET_ID=1Mxxx
export GCP_SERVICE_ACCOUNT='{...}'
python report_generator.py morning
```

---

## 🔐 Security

- All secrets via local `.env` / GitHub Secrets / Streamlit Secrets — zero hardcoded keys
- Google Sheets Service Account with minimal permissions (editor only)
- `.gitignore` excludes all credential files and interview-prep docs

---

## 🔮 Future Roadmap

- [ ] Migrate Google Sheets → PostgreSQL for >100 users
- [ ] Add more data sources (bond market, crypto)
- [ ] Multi-language report support (EN/CN)
- [ ] Docker deployment
- [ ] Backtesting engine for strategy evaluation

---

## 📄 License

MIT

---

# 中文

## 📊 金融研报 Agent

> 覆盖全部 A 股（5000+）和公募基金（10000+）的 AI 智能分析工具。**核心是 Agent 自主决策**——不是简单的问答机器人。

## 🎬 演示

<!-- TODO: 录屏后替换 -->
> *Demo 视频制作中*

**快速体验：**
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 🧠 Agent 核心能力

手写 Agent Loop（约 50 行），实现 **7 个 Tool-use 工具**，Agent 自主决定调用哪些工具、调用顺序、何时输出最终结果——无需人工编写 if-else。

**持仓导入**：Web 端上传券商/天天基金导出的 CSV/Excel，自动识别列名、预览确认后导入持仓，并可一键保存到每日推送名单。

## 🏗 系统架构

```
Streamlit 网页注册 → Google Sheets 存持仓
                         ↓
          本机 crontab 定时触发（交易日 10:00 / 14:30）
                         ↓
          数据采集 → DeepSeek AI 分析 → 报告生成
                         ↓
          ┌─ cc-connect → 微信 Bot 好友（电脑在线）
          └─ Server酱 ──→ 公众号推送（兜底）
```

> 多用户时在 Google Sheets 增加 `cc_target` 列（或本地 JSON 字段）；不配置则只走 Server酱，避免串号。

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| AI 模型 | DeepSeek V4（Anthropic 兼容 API） |
| 数据源 | 新浪财经 / 东方财富 / 天天基金 |
| 数据存储 | Google Sheets（零成本，支持本地回退） |
| 定时调度 | 本机 crontab（GitHub Actions 保留手动触发） |
| 消息推送 | cc-connect (iLink Bot) + Server酱（双通道自动切换） |
| 前端 | Streamlit |
| 月度成本 | **¥0** |
