# 📊 金融研报 Agent

> 覆盖全部 A 股（5000+）和公募基金（10000+）的智能分析工具，支持多用户自动推送。

## 🏗 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        用户层                                 │
│  Streamlit 网页  │  Google Form 注册  │  Google Sheets 管理    │
└────────────────────────┬─────────────────────────────────────┘
                         │ 读写
┌────────────────────────▼─────────────────────────────────────┐
│                    数据层 (Google Sheets)                     │
│  用户表: name | code | item_name | type | alert              │
└────────────────────────┬─────────────────────────────────────┘
                         │ 读取
┌────────────────────────▼─────────────────────────────────────┐
│                   定时调度 (GitHub Actions)                    │
│  cron: 10:00 & 14:30 BJT (UTC 2:00 & 6:30) Mon-Fri          │
│  失败自动告警 → 微信                                          │
└────────────────────────┬─────────────────────────────────────┘
                         │ 触发
┌────────────────────────▼─────────────────────────────────────┐
│                   报告生成引擎 (Python)                        │
│  市场数据采集 → AI 分析 → 报告生成                              │
└────────────────────────┬─────────────────────────────────────┘
                         │ 推送
┌──────────────────────────────────────────────────────────────┐
│                    微信通知 (Server酱)                         │
│  每个交易日两篇报告 + 失败告警                                  │
└──────────────────────────────────────────────────────────────┘
```

## 🎯 核心设计决策

### 1. 为什么用 Google Sheets 当数据库？

| 方案 | 成本 | 复杂度 | 用户注册 |
|------|------|------|------|
| GitHub 文件存储 | 免费 | 低 | ❌ 需要 Commit |
| MySQL/PostgreSQL | 付费 | 高 | ✅ |
| **Google Sheets** | 免费 | 低 | ✅ 网页直接写入 |

对于用户量 < 100 的场景，Google Sheets 完全够用，且提供免费的 Web UI 管理能力。

### 2. 为什么用 GitHub Actions 而不是云服务器？

- 传统方案：阿里云 ECS ≈ ¥50-200/月
- 本方案：GitHub Actions 免费（每月 2000 分钟，私有仓库），日耗 ≈ 2 分钟
- **节省成本 > ¥600/年**

同时 GitHub Actions 提供了：
- 完整的日志和运行历史
- 失败自动邮件通知
- 手动触发和重新运行

### 3. 容错设计

```
读取用户 → Google Sheets 优先 → 失败回退本地 JSON 文件
生成报告 → DeepSeek API    → 失败推微信告警
定时调度 → GitHub Actions   → 失败自动发 Server酱通知
```

## 🛠 技术栈

| 层级 | 技术 | 选型理由 |
|------|------|------|
| 前端 | Streamlit | Python 生态，零前端代码即可构建数据 App |
| AI | DeepSeek V4 | 通过 Anthropic 兼容 API 调用，成本远低于 Claude |
| 数据 | 新浪财经 / 东方财富 / 天天基金 | 免费公开 API，覆盖 A 股全部标的 |
| 存储 | Google Sheets + gspread | 零成本用户数据管理，Service Account 鉴权 |
| 调度 | GitHub Actions | 免费 cron，与代码仓库深度集成 |
| 推送 | Server酱 (ftqq.com) | 免费微信推送通道，API 简单 |
| 部署 | Streamlit Cloud | 免费托管，自动关联 GitHub |

## 📁 项目结构

```
finance-agent/
├── app.py                  # Streamlit 网页应用（分析 + 用户注册）
├── report_generator.py     # 报告生成引擎（定时任务入口）
├── sheets_db.py            # Google Sheets 数据访问层
├── users/                  # 用户配置（本地回退，开发用）
├── config.json             # 全局配置（自选列表、告警阈值）
├── requirements.txt        # Python 依赖
├── .github/workflows/      # GitHub Actions 定时调度
│   └── daily-report.yml    # 每个交易日 10:00 & 14:30 触发
└── README.md
```

## 🚀 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动网页界面
streamlit run app.py

# 手动生成报告（需设置环境变量）
ANTHROPIC_API_KEY=sk-xxx \
SERVERCHAN_SENDKEY=SCTxxx \
GOOGLE_SHEET_ID=1Mxxx \
GCP_SERVICE_ACCOUNT='{...}' \
python report_generator.py morning
```

## 🔐 安全实践

- 所有 API Key 和密钥通过 GitHub Secrets / Streamlit Secrets 注入，代码中零硬编码
- 仓库保持私有
- Google Sheets 仅授权 Service Account，不对外暴露
- Service Account 权限最小化（仅 Sheet 编辑者）

## 📊 数据流

```
1. 用户注册 → Streamlit 填写持仓 → Google Sheets append_row
2. 定时触发 → GitHub Actions cron → Python 脚本
3. Python 脚本:
   a. 判断交易日（新浪 API 验证）
   b. 读取用户（Google Sheets + 本地回退）
   c. 采集行情（多源聚合）
   d. AI 分析（DeepSeek Anthropic API）
   e. 推送微信（Server酱）
4. 失败处理 → Server酱 告警 + GitHub Actions 邮件通知
```

