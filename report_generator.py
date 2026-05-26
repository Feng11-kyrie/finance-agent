"""
定时报告生成器 - 早盘 & 午盘分析
GitHub Actions 定时触发，通过 PushPlus 推送到微信
工作日自动运行，周末和节假日自动跳过
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import anthropic
import requests

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════

BEIJING_TZ = timezone(timedelta(hours=8))
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


def is_trading_day() -> tuple[bool, str]:
    """判断今天是否为 A 股交易日。返回 (是否交易日, 原因)"""
    now = datetime.now(BEIJING_TZ)

    # 1. 周末直接跳过
    if now.weekday() >= 5:
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return False, f"今天是{weekday_names[now.weekday()]}，A股休市"

    # 2. 检查市场是否真的在交易（上证指数成交量 > 0 说明开盘）
    try:
        r = requests.get(
            "https://hq.sinajs.cn/list=sh000001",
            headers=SINA_HEADERS, timeout=8,
        )
        r.encoding = "gbk"
        parts = r.text.split('"')[1].split(",")
        volume = int(parts[8]) if parts[8] else 0
        if volume == 0:
            return False, "上证指数无成交量，判断为非交易日（节假日休市）"
    except Exception as e:
        # 数据获取失败，保守起见跳过
        return False, f"无法确认市场状态: {e}"

    # 3. 检查是否在交易时间之外（非交易时间也能发，但不跳过）
    hour = now.hour
    minute = now.minute
    if hour < 9 or (hour == 9 and minute < 15):
        return True, f"盘前 ({now:%H:%M})"
    elif hour < 11 or (hour == 11 and minute <= 30):
        return True, f"早盘交易中 ({now:%H:%M})"
    elif hour < 13:
        return True, f"午间休市 ({now:%H:%M})"
    elif hour < 15:
        return True, f"午盘交易中 ({now:%H:%M})"
    else:
        return True, f"已收盘 ({now:%H:%M})"

    return True, ""

# PushPlus token — 从环境变量或 secrets 读取
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

# ═══════════════════════════════════════════════
# 推送（Server酱）
# ═══════════════════════════════════════════════

def push_to_wechat(title: str, content: str) -> bool:
    """通过 Server酱 推送到微信"""
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "")
    if not sendkey:
        print("⚠️ 未配置 SERVERCHAN_SENDKEY，跳过推送")
        return False

    try:
        # Server酱支持 Markdown，用 desp 参数传内容
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content},
            timeout=15,
        )
        result = r.json()
        if result.get("code") == 0:
            print(f"✅ 推送成功: {title}")
            return True
        else:
            print(f"❌ 推送失败: {result}")
            return False
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        return False
# 用户持仓配置路径
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.json")


# ═══════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════

def get_market_indices() -> dict:
    """获取主要大盘指数"""
    indices = {
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "创业板指": "sz399006",
        "沪深300": "sh000300",
        "科创50": "sh000688",
    }
    results = {}
    session = requests.Session()
    session.headers.update(SINA_HEADERS)
    for name, code in indices.items():
        try:
            r = session.get(f"https://hq.sinajs.cn/list={code}", timeout=8)
            r.encoding = "gbk"
            parts = r.text.split('"')[1].split(",")
            results[name] = {
                "name": parts[0],
                "price": float(parts[3]),
                "change_pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2),
                "high": float(parts[4]),
                "low": float(parts[5]),
                "volume": int(parts[8]) if parts[8] else 0,
            }
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


def get_hot_sectors() -> list[dict]:
    """获取热门板块（用概念板块替代）"""
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "8", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:90+t:3",  # 概念板块
            "fields": "f2,f3,f4,f12,f14",
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        results = []
        for item in data.get("data", {}).get("diff", []):
            results.append({
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
            })
        return results
    except Exception:
        return []


def get_holding_summary() -> str:
    """读取用户持仓数据并获取实时行情摘要"""
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
    except Exception:
        return "暂无持仓数据"

    lines = []
    stocks = config.get("watchlist", {}).get("stocks", [])
    funds = config.get("watchlist", {}).get("funds", [])

    # 股票持仓
    for s in stocks[:10]:  # 最多查10只
        code = s.get("code", "")
        prefix = "sh" if code.startswith("6") else "sz"
        try:
            r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                             headers=SINA_HEADERS, timeout=8)
            r.encoding = "gbk"
            parts = r.text.split('"')[1].split(",")
            price = float(parts[3])
            prev = float(parts[2])
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0
            lines.append(
                f"{s['name']}({code}): ¥{price:.2f} ({change_pct:+.2f}%), "
                f"今日高{parts[4]} 低{parts[5]}"
            )
        except Exception:
            lines.append(f"{s.get('name', code)}({code}): 获取失败")

    # 基金持仓
    for f_item in funds[:5]:
        code = f_item.get("code", "")
        try:
            r = requests.get(f"https://fundgz.1234567.com.cn/js/{code}.js", timeout=8)
            match = re.search(r"jsonpgz\((.+)\)", r.text)
            if match:
                data = json.loads(match.group(1))
                lines.append(
                    f"{data.get('name', code)}({code}): "
                    f"净值 {data.get('dwjz', '?')}, "
                    f"估算 {data.get('gsz', '?')} ({float(data.get('gszzl', 0)):+.2f}%)"
                )
        except Exception:
            lines.append(f"{f_item.get('name', code)}({code}): 获取失败")

    return "\n".join(lines) if lines else "暂无持仓"


def get_total_market_summary() -> str:
    """获取全市场概况（涨跌家数等）"""
    try:
        # 获取涨停/跌停数量简况
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "1", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12", "fid": "f3", "po": "0",
            },
            timeout=8,
        )
        if r.status_code == 200:
            total = r.json().get("data", {}).get("total", 0)
            return f"A股上市公司总数: {total}"
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════
# Agent 报告生成
# ═══════════════════════════════════════════════

def generate_report(report_type: str) -> str:
    """
    report_type: "morning" | "afternoon"
    """
    # 获取所有数据
    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 获取大盘指数...")
    indices = get_market_indices()

    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 获取热点板块...")
    sectors = get_hot_sectors()

    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 获取持仓数据...")
    holdings = get_holding_summary()

    # 整理数据
    index_lines = []
    for name, d in indices.items():
        if "error" not in d:
            index_lines.append(
                f"- {name}: {d['price']:.2f} ({d['change_pct']:+.2f}%), "
                f"最高{d['high']:.2f} 最低{d['low']:.2f}"
            )

    sector_lines = []
    for s in sectors:
        sector_lines.append(f"- {s['name']}: {s['change_pct']:+.2f}%")

    # 构造 prompt
    if report_type == "morning":
        time_desc = "上午 10:00（开盘 30 分钟）"
        focus = (
            "1. 今日大盘开盘情况综述（哪些指数强势/弱势）\n"
            "2. 当前热点板块及资金流向分析\n"
            "3. 用户持仓个股的板块表现\n"
            "4. 今日操作建议：哪些可关注、哪些要警惕\n"
            "5. 给出今日最值得关注的 2-3 个方向"
        )
    else:
        time_desc = "下午 14:30（收盘前最后半小时）"
        focus = (
            "1. 今日全天盘面总结（指数走势、风格切换）\n"
            "2. 热点板块持续性分析\n"
            "3. 用户持仓个股的全天表现及问题诊断\n"
            "4. 明日大盘走势预测\n"
            "5. 持仓优化建议（哪些该留、哪些该减、是否有调仓机会）\n"
            "6. 给出明天最值得关注的 2-3 个方向"
        )

    prompt = (
        f"当前时间：{time_desc}\n"
        f"日期：{datetime.now(BEIJING_TZ):%Y年%m月%d日}\n\n"
        f"## 大盘指数\n"
        + "\n".join(index_lines) +
        f"\n\n## 热门板块\n"
        + "\n".join(sector_lines if sector_lines else ["板块数据暂未获取到"]) +
        f"\n\n## 用户持仓\n{holdings}\n\n"
        f"请基于以上数据生成一份专业的A股{report_type}报告，要求：\n"
        f"{focus}\n\n"
        f"回复格式：Markdown，简洁有力。开头写「📊 A股{report_type}报告 | {datetime.now(BEIJING_TZ):%m月%d日}」"
        f"结尾标注「🤖 由金融研报Agent自动生成 | {datetime.now(BEIJING_TZ):%H:%M}」"
        f"不要有免责声明或投资建议警告。"
    )

    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 调用 Agent 生成报告...")
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
    )

    response = client.messages.create(
        model="deepseek-v4-flash",
        max_tokens=3072,
        system="你是一位专业A股分析师。根据提供的市场数据生成高质量分析报告。",
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


# ═══════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════

def main():
    now = datetime.now(BEIJING_TZ)

    # ── 交易日检查 ──
    trading, reason = is_trading_day()
    print(f"交易日检查: {'✅ 是' if trading else '❌ 否'} — {reason}")
    if not trading:
        print(f"跳过报告生成: {reason}")
        return  # 优雅退出，不报错

    # 根据时间自动判断报告类型
    if len(sys.argv) > 1:
        report_type = sys.argv[1]  # "morning" or "afternoon"
    else:
        hour = now.hour
        report_type = "morning" if hour < 12 else "afternoon"

    print(f"开始生成 {report_type} 报告... 时间: {now:%Y-%m-%d %H:%M:%S}")

    try:
        report = generate_report(report_type)
        print(f"报告生成完成，长度: {len(report)} 字符")

        # 推送
        cn_type = "早盘" if report_type == "morning" else "午盘"
        title = f"📊 A股{cn_type}报告 | {now:%m月%d日}"
        push_to_wechat(title, report)

        # 同时输出到控制台（供 GitHub Actions 日志查看）
        print("\n" + "=" * 60)
        print(report)
        print("=" * 60)

    except Exception as e:
        import traceback
        traceback.print_exc()
        # 推送错误通知
        push_to_wechat(
            f"❌ 报告生成失败 | {now:%m月%d日}",
            f"**错误信息**\n```\n{traceback.format_exc()[:500]}\n```"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
