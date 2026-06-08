"""
定时报告生成器 - 早盘 & 闭盘前分析
GitHub Actions 定时触发，通过 Server酱 推送到微信
多用户支持：读取 users/ 目录下所有配置文件，各自推送
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import anthropic
import requests

# 导入 Google Sheets 数据库
import sheets_db

BEIJING_TZ = timezone(timedelta(hours=8))
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


# ═══════════════════════════════════════════════
# 交易日判断
# ═══════════════════════════════════════════════

def is_trading_day() -> tuple[bool, str]:
    now = datetime.now(BEIJING_TZ)
    if now.weekday() >= 5:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return False, f"今天是{names[now.weekday()]}，A股休市"
    try:
        r = requests.get("https://hq.sinajs.cn/list=sh000001", headers=SINA_HEADERS, timeout=8)
        r.encoding = "gbk"
        parts = r.text.split('"')[1].split(",")
        if int(parts[8]) == 0:
            return False, "上证指数无成交量，判断为非交易日（节假日休市）"
    except Exception as e:
        return False, f"无法确认市场状态: {e}"
    return True, ""


# ═══════════════════════════════════════════════
# 用户管理
# ═══════════════════════════════════════════════

def load_all_users() -> list[dict]:
    """加载用户（优先 Google Sheets，失败回退本地文件）"""
    return sheets_db.load_all_users()


# ═══════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════

def get_market_indices() -> dict:
    indices = {
        "上证指数": "sh000001", "深证成指": "sz399001",
        "创业板指": "sz399006", "沪深300": "sh000300", "科创50": "sh000688",
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
                "high": float(parts[4]), "low": float(parts[5]),
                "volume": int(parts[8]) if parts[8] else 0,
            }
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


def get_hot_sectors() -> list[dict]:
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get", params={
            "pn": "1", "pz": "8", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:90+t:3", "fields": "f2,f3,f4,f12,f14",
        }, timeout=10)
        results = []
        for item in r.json().get("data", {}).get("diff", []):
            results.append({"name": item.get("f14", ""), "change_pct": item.get("f3", 0)})
        return results
    except Exception:
        return []


def get_holdings_for_user(user: dict) -> str:
    watchlist = user.get("watchlist", {})
    lines = []

    for s in watchlist.get("stocks", [])[:10]:
        code = s.get("code", "")
        # 确保股票代码是6位（Google Sheets 可能吞掉前导零）
        code = code.zfill(6)
        prefix = "sh" if code.startswith("6") else "sz"
        try:
            r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                             headers=SINA_HEADERS, timeout=8)
            r.encoding = "gbk"
            parts = r.text.split('"')[1].split(",")
            price, prev = float(parts[3]), float(parts[2])
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0
            lines.append(
                f"{s['name']}({code}): ¥{price:.2f} ({change_pct:+.2f}%), "
                f"高{parts[4]} 低{parts[5]}"
            )
        except Exception:
            lines.append(f"{s.get('name', code)}({code}): 获取失败")

    for f_item in watchlist.get("funds", [])[:10]:
        code = f_item.get("code", "")
        # 确保基金代码是6位（Google Sheets 可能吞掉前导零）
        code = code.zfill(6)
        try:
            r = requests.get(f"https://fundgz.1234567.com.cn/js/{code}.js", timeout=8)
            match = re.search(r"jsonpgz\((.+)\)", r.text)
            if match:
                d = json.loads(match.group(1))
                lines.append(
                    f"{d.get('name', code)}({code}): "
                    f"净值{d.get('dwjz','?')}, 估算{d.get('gsz','?')} "
                    f"({float(d.get('gszzl',0)):+.2f}%)"
                )
            else:
                lines.append(f"{f_item.get('name', code)}({code}): API返回异常")
        except Exception:
            lines.append(f"{f_item.get('name', code)}({code}): 获取失败")

    return "\n".join(lines) if lines else "暂无持仓"


# ═══════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════

def generate_report(report_type: str, user: dict) -> str:
    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 为用户 {user.get('name','?')} 生成报告...")

    indices = get_market_indices()
    sectors = get_hot_sectors()
    holdings = get_holdings_for_user(user)

    index_lines = []
    for name, d in indices.items():
        if "error" not in d:
            index_lines.append(
                f"- {name}: {d['price']:.2f} ({d['change_pct']:+.2f}%), "
                f"最高{d['high']:.2f} 最低{d['low']:.2f}"
            )
    sector_lines = [f"- {s['name']}: {s['change_pct']:+.2f}%" for s in sectors]

    if report_type == "morning":
        time_desc = "上午 10:00（开盘 30 分钟）"
        focus = (
            "1. 今日大盘开盘情况综述（哪些指数强势/弱势）\n"
            "2. 当前热点板块及资金流向分析\n"
            "3. 用户每支持仓基金的开盘表现：逐个点评涨跌原因\n"
            "4. 持仓结构诊断：分析行业集中度、板块重叠风险\n"
            "5. 今日操作建议：哪些可关注、哪些要警惕，具体到每支基金\n"
            "6. 给出今日最值得关注的 2-3 个方向"
        )
    else:
        time_desc = "下午 14:10（收盘前 50 分钟）"
        focus = (
            "1. 今日全天盘面总结（指数走势、风格切换）\n"
            "2. 热点板块持续性分析\n"
            "3. 用户每支持仓基金的全天表现：逐个诊断涨跌原因和趋势\n"
            "4. 持仓结构深度诊断：\n"
            "   - 行业集中度：持仓基金的底层资产是否过度集中在某个赛道\n"
            "   - 重叠风险：哪些基金买了类似的重仓股，存在共振风险\n"
            "   - 风险等级评估：组合整体波动率判断\n"
            "   - 对冲分析：是否有相互对冲的持仓\n"
            "5. 明日大盘走势预测\n"
            "6. 调仓建议（具体到每支基金）：\n"
            "   - 哪些该继续持有并加仓\n"
            "   - 哪些该减仓或清仓\n"
            "   - 建议新增什么类型的基金来优化组合\n"
            "7. 长期配置建议：你的组合缺少什么类型的资产（如债券、消费、医药等）"
        )

    # 构建持仓清单（强制逐支列出）
    holding_lines = holdings.strip().split("\n")
    holding_list = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(holding_lines) if h.strip())

    prompt = (
        f"当前时间：{time_desc}\n"
        f"日期：{datetime.now(BEIJING_TZ):%Y年%m月%d日}\n"
        f"用户名：{user.get('name','')}\n\n"
        f"## 大盘指数\n" + "\n".join(index_lines) +
        f"\n\n## 热门板块\n" + "\n".join(sector_lines or ["暂无数据"]) +
        f"\n\n## 用户持仓（共 {len([h for h in holding_lines if h.strip()])} 支）\n{holding_list}\n\n"
        f"请基于以上数据生成一份专业的A股{report_type}报告，要求：\n{focus}\n\n"
        f"⚠️ 重要格式要求：\n"
        f"1. 对以上列出的每一支持仓，必须单独列一个小标题（### 基金名），下面写100-150字分析\n"
        f"2. 逐支诊断时，必须写明：今日表现 -> 涨跌原因 -> 操作建议（持有/加仓/减仓）\n"
        f"3. 不许合并、不许省略、不许用「等」字跳过\n"
        f"4. 开头写「📊 A股{report_type}报告 | "
        f"{datetime.now(BEIJING_TZ):%m月%d日} | {user.get('name','')}」\n"
        f"5. 结尾标注「🤖 由金融研报Agent自动生成 | {datetime.now(BEIJING_TZ):%H:%M}」\n"
        f"6. 不要写免责声明或投资建议警告"
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未配置")

    client = anthropic.Anthropic(api_key=api_key, base_url="https://api.deepseek.com/anthropic")
    print(f"  调用 deepseek-chat, prompt {len(prompt)} 字符")

    response = client.messages.create(
        model="deepseek-chat", max_tokens=4096,
        system="你是一位专业A股分析师，你的核心职责是对用户的每支持仓基金进行逐一深度诊断。你必须遵守以下规则：1) 每支基金必须单独分析，用 ### 标题列出；2) 不能合并、不能省略、不能只说「整体来看」；3) 每支基金至少写 100 字分析。",
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return response.content[0].text


# ═══════════════════════════════════════════════
# 推送
# ═══════════════════════════════════════════════

import subprocess


def _push_via_cc_connect(content: str) -> bool:
    """通过 cc-connect 推送到微信 Bot 好友"""
    try:
        result = subprocess.run(
            ["cc-connect", "send", "--stdin", "-p", "main"],
            input=content.encode(),
            timeout=30,
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _push_via_serverchan(user: dict, title: str, content: str) -> bool:
    """通过 Server酱 推送到微信（兜底方案）"""
    sendkey = user.get("sendkey", "") or os.environ.get("SERVERCHAN_SENDKEY", "")
    if not sendkey:
        print(f"  ⚠️ {user.get('name','?')} 未配置 sendkey，跳过")
        return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content}, timeout=15,
        )
        if r.json().get("code") == 0:
            return True
        else:
            print(f"  ❌ Server酱推送失败: {r.json()}")
            return False
    except Exception as e:
        print(f"  ❌ Server酱推送异常: {e}")
        return False


def push_to_user(user: dict, title: str, content: str) -> bool:
    """
    智能推送：优先微信 Bot（cc-connect），电脑未开机时回退 Server酱。
    不会重复推送。
    """
    name = user.get("name", "?")

    # 先试 cc-connect（电脑开着就能推微信 Bot）
    if _push_via_cc_connect(content):
        print(f"  ✅ [微信Bot] 已推送给 {name}")
        return True

    # cc-connect 没运行 → 电脑关了 → 回退 Server酱
    print(f"  ⚠️ cc-connect 不可用，回退 Server酱...")
    if _push_via_serverchan(user, title, content):
        print(f"  ✅ [Server酱] 已推送给 {name}")
        return True

    print(f"  ❌ 所有推送方式均失败")
    return False


# ═══════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════

def main():
    now = datetime.now(BEIJING_TZ)

    explicit_type = len(sys.argv) > 1
    if explicit_type:
        report_type = sys.argv[1]
    else:
        report_type = "morning" if now.hour < 12 else "afternoon"

    # 时间窗口保护：仅在未明确指定类型时检查（手动运行时）
    # GitHub Actions 明确传参时跳过检查，因为 cron 可能延迟导致北京 time 跑偏
    if not explicit_type:
        if report_type == "morning":
            if not (9 <= now.hour < 12):
                print(f"跳过: 早盘报告时间窗口为 9:00-12:00，当前 {now:%H:%M}")
                return
        else:
            if not (14 <= now.hour < 17):
                print(f"跳过: 闭盘前报告时间窗口为 14:00-17:00，当前 {now:%H:%M}")
                return

    trading, reason = is_trading_day()
    print(f"交易日检查: {'✅ 是' if trading else '❌ 否'} — {reason}")
    if not trading:
        print(f"跳过报告: {reason}")
        return

    cn_type = "早盘" if report_type == "morning" else "闭盘前"
    print(f"开始生成 {cn_type}报告 | {now:%Y-%m-%d %H:%M:%S}")

    users = load_all_users()
    print(f"加载了 {len(users)} 个用户")

    if not users:
        print("⚠️ users/ 目录下没有用户配置，请添加 JSON 文件")
        return

    success = 0
    for user in users:
        try:
            report = generate_report(report_type, user)
            title = f"📊 A股{cn_type}报告 | {now:%m月%d日}"
            if push_to_user(user, title, report):
                success += 1
        except Exception as e:
            import traceback
            print(f"❌ 用户 {user.get('name','?')} 报告生成失败:")
            traceback.print_exc()
            push_to_user(user, f"❌ 报告生成失败", f"```\n{traceback.format_exc()[:300]}\n```")

    print(f"\n完成: {success}/{len(users)} 个用户推送成功")


if __name__ == "__main__":
    main()
