"""
定时报告生成器 - 早盘 & 午盘分析
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

BEIJING_TZ = timezone(timedelta(hours=8))
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
USERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users")


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
    users = []
    if not os.path.isdir(USERS_DIR):
        return users
    for fname in sorted(os.listdir(USERS_DIR)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(USERS_DIR, fname)) as f:
                    user = json.load(f)
                    user["_file"] = fname
                    users.append(user)
            except Exception:
                pass
    return users


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
            "3. 用户持仓的板块表现\n"
            "4. 今日操作建议：哪些可关注、哪些要警惕\n"
            "5. 给出今日最值得关注的 2-3 个方向"
        )
    else:
        time_desc = "下午 14:30（收盘前最后半小时）"
        focus = (
            "1. 今日全天盘面总结（指数走势、风格切换）\n"
            "2. 热点板块持续性分析\n"
            "3. 用户持仓的全天表现及问题诊断\n"
            "4. 明日大盘走势预测\n"
            "5. 持仓优化建议（哪些该留、哪些该减、是否有调仓机会）\n"
            "6. 给出明天最值得关注的 2-3 个方向"
        )

    prompt = (
        f"当前时间：{time_desc}\n"
        f"日期：{datetime.now(BEIJING_TZ):%Y年%m月%d日}\n"
        f"用户名：{user.get('name','')}\n\n"
        f"## 大盘指数\n" + "\n".join(index_lines) +
        f"\n\n## 热门板块\n" + "\n".join(sector_lines or ["暂无数据"]) +
        f"\n\n## 用户持仓\n{holdings}\n\n"
        f"请基于以上数据生成一份专业的A股{report_type}报告，要求：\n{focus}\n\n"
        f"回复格式：Markdown，简洁有力。开头写「📊 A股{report_type}报告 | "
        f"{datetime.now(BEIJING_TZ):%m月%d日} | {user.get('name','')}」"
        f"结尾标注「🤖 由金融研报Agent自动生成 | {datetime.now(BEIJING_TZ):%H:%M}」"
        f"不要写免责声明或投资建议警告。"
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未配置")

    client = anthropic.Anthropic(api_key=api_key, base_url="https://api.deepseek.com/anthropic")
    print(f"  调用 deepseek-chat, prompt {len(prompt)} 字符")

    response = client.messages.create(
        model="deepseek-chat", max_tokens=3072,
        system="你是一位专业A股分析师。根据提供的市场数据生成高质量分析报告。",
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return response.content[0].text


# ═══════════════════════════════════════════════
# 推送
# ═══════════════════════════════════════════════

def push_to_user(user: dict, title: str, content: str) -> bool:
    sendkey = user.get("sendkey", "")
    if not sendkey:
        print(f"  ⚠️ {user.get('name','?')} 未配置 sendkey，跳过")
        return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content}, timeout=15,
        )
        if r.json().get("code") == 0:
            print(f"  ✅ 已推送给 {user.get('name','?')}")
            return True
        else:
            print(f"  ❌ 推送失败: {r.json()}")
            return False
    except Exception as e:
        print(f"  ❌ 推送异常: {e}")
        return False


# ═══════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════

def main():
    now = datetime.now(BEIJING_TZ)

    trading, reason = is_trading_day()
    print(f"交易日检查: {'✅ 是' if trading else '❌ 否'} — {reason}")
    if not trading:
        print(f"跳过报告: {reason}")
        return

    if len(sys.argv) > 1:
        report_type = sys.argv[1]
    else:
        report_type = "morning" if now.hour < 12 else "afternoon"

    cn_type = "早盘" if report_type == "morning" else "午盘"
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
