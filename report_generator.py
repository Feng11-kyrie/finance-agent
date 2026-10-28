"""
定时报告生成器 - 早盘 & 闭盘前分析
GitHub Actions 定时触发，通过 Server酱 推送到微信
多用户支持：读取 users/ 目录下所有配置文件，各自推送
"""

import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta

import anthropic
import requests

from config_loader import get_model
from data_api import api_stock_quote, api_fund_valuation

# 导入 Google Sheets 数据库
import sheets_db

BEIJING_TZ = timezone(timedelta(hours=8))
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
# 东财板块接口必须带 quote 站 Referer，否则会直接断开连接
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"


# ═══════════════════════════════════════════════
# 交易日判断
# ═══════════════════════════════════════════════

def is_trading_day() -> tuple[bool, str]:
    now = datetime.now(BEIJING_TZ)
    if now.weekday() >= 5:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return False, f"今天是{names[now.weekday()]}，A股休市"

    last_error = None
    for _ in range(2):
        try:
            r = requests.get("https://hq.sinajs.cn/list=sh000001", headers=SINA_HEADERS, timeout=8)
            r.encoding = "gbk"
            parts = r.text.split('"')[1].split(",")
            if int(parts[8]) == 0:
                return False, "上证指数无成交量，判断为非交易日（节假日休市）"
            return True, ""
        except Exception as e:
            last_error = e

    # 网络异常不能当成“休市”，否则会静默漏报一整天。
    # 按交易日继续，让后续取数失败在报告里显式暴露出来（并有熔断兜底）。
    return True, f"无法确认市场状态（{last_error}），按交易日继续"


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


def _get_sina_sectors(limit: int = 8) -> list[dict]:
    """东财板块接口被限流时的备源：新浪行业板块。"""
    try:
        r = requests.get(
            "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            headers=SINA_HEADERS, timeout=10,
        )
        r.encoding = "gbk"
        rows = []
        for raw in re.findall(r'"[^"]+":"([^"]+)"', r.text):
            parts = raw.split(",")
            if len(parts) < 6:
                continue
            try:
                change = float(parts[5])
            except ValueError:
                continue
            rows.append({"name": parts[1], "change_pct": round(change, 2)})
        rows.sort(key=lambda x: x["change_pct"], reverse=True)
        return rows[:limit]
    except Exception:
        return []


def get_hot_sectors() -> list[dict]:
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get", params={
            "pn": "1", "pz": "8", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3", "ut": EM_UT,
            "fs": "m:90+t:3", "fields": "f2,f3,f4,f12,f14",
        }, headers=EM_HEADERS, timeout=10)
        diff = (r.json().get("data") or {}).get("diff") or []
        results = []
        for item in diff:
            change = item.get("f3", 0)
            try:
                change = float(change)
            except (TypeError, ValueError):
                change = 0
            results.append({"name": item.get("f14", ""), "change_pct": change})
        if results:
            return results
    except Exception:
        pass

    # 东财空响应/限流时用新浪行业板块兜底
    return _get_sina_sectors()


def get_holdings_for_user(user: dict) -> tuple[str, int, int]:
    """返回 (持仓文本, 成功条数, 总条数)。

    统一走 data_api，避免这里再维护一套新浪/天天基金的解析逻辑。
    多返回两个计数，是为了在报告生成前做“全部取数失败”熔断。
    """
    watchlist = user.get("watchlist", {})
    lines: list[str] = []
    ok = 0
    total = 0

    for s in watchlist.get("stocks", [])[:10]:
        total += 1
        code = str(s.get("code", "")).zfill(6)
        quote = api_stock_quote(code)
        if quote and quote.get("price"):
            change_pct = quote.get("change_pct", 0)
            lines.append(
                f"{quote.get('name') or s.get('name', code)}({code}): "
                f"¥{quote['price']:.2f} ({change_pct:+.2f}%), "
                f"高{quote.get('high', 0)} 低{quote.get('low', 0)}"
            )
            ok += 1
        else:
            lines.append(f"{s.get('name', code)}({code}): 获取失败")

    for f_item in watchlist.get("funds", [])[:10]:
        total += 1
        code = str(f_item.get("code", "")).zfill(6)
        val = api_fund_valuation(code)
        if val and val.get("nav"):
            if val.get("is_estimate"):
                desc = (
                    f"净值{val['nav']:.4f}, 估算{val['estimated_nav']:.4f} "
                    f"({val['estimated_change_pct']:+.2f}%)"
                )
            else:
                desc = f"净值{val['nav']:.4f} ({val['estimated_change_pct']:+.2f}%, 无实时估值)"
            lines.append(f"{val.get('name') or f_item.get('name', code)}({code}): {desc}")
            ok += 1
        else:
            lines.append(f"{f_item.get('name', code)}({code}): 获取失败")

    return ("\n".join(lines) if lines else "暂无持仓"), ok, total


# ═══════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════

def _extract_text(response) -> str:
    """只取 text block，忽略 thinking / redacted_thinking 等块。"""
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", "") == "text"
    )


def _create_with_retry(client, **kwargs) -> str:
    """模型偶尔只返回 thinking 块（没有 text），重试一次再报错。"""
    block_types = []
    for attempt in range(2):
        response = client.messages.create(**kwargs)
        text = _extract_text(response)
        if text.strip():
            return text
        block_types = [getattr(b, "type", "?") for b in response.content]
        print(f"  ⚠️ 第 {attempt + 1} 次模型只返回 {block_types}，重试...")
    raise RuntimeError(f"模型连续 2 次没有返回文本内容（blocks: {block_types}）")


def generate_report(report_type: str, user: dict) -> str:
    print(f"[{datetime.now(BEIJING_TZ):%H:%M:%S}] 为用户 {user.get('name','?')} 生成报告...")

    indices = get_market_indices()
    sectors = get_hot_sectors()
    holdings, ok_count, total_count = get_holdings_for_user(user)

    # 熔断：没有任何可用行情时不要调用模型，否则报告只能靠编
    if indices and all("error" in d for d in indices.values()):
        raise RuntimeError("大盘指数全部获取失败，已终止生成")
    if total_count and ok_count == 0:
        raise RuntimeError(
            f"{total_count} 支持仓行情全部获取失败，已终止生成（避免输出无依据报告）"
        )

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
            "3. 用户每个持仓标的的开盘表现：逐个点评涨跌原因\n"
            "4. 持仓结构诊断：分析行业集中度、板块重叠风险\n"
            "5. 今日操作建议：哪些可关注、哪些要警惕，具体到每个标的\n"
            "6. 给出今日最值得关注的 2-3 个方向"
        )
    else:
        time_desc = "下午 14:30（收盘前 30 分钟）"
        focus = (
            "1. 今日全天盘面总结（指数走势、风格切换）\n"
            "2. 热点板块持续性分析\n"
            "3. 用户每个持仓标的的全天表现：逐个诊断涨跌原因和趋势\n"
            "4. 持仓结构深度诊断：\n"
            "   - 行业集中度：持仓标的的底层资产是否过度集中在某个赛道\n"
            "   - 重叠风险：哪些标的买了类似的重仓股，存在共振风险\n"
            "   - 风险等级评估：组合整体波动率判断\n"
            "   - 对冲分析：是否有相互对冲的持仓\n"
            "5. 明日大盘走势预测\n"
            "6. 调仓建议（具体到每个标的）：\n"
            "   - 哪些该继续持有并加仓\n"
            "   - 哪些该减仓或清仓\n"
            "   - 建议新增什么类型的基金来优化组合\n"
            "7. 长期配置建议：你的组合缺少什么类型的资产（如债券、消费、医药等）"
        )

    # 构建持仓清单（强制逐支列出）
    holding_lines = [h for h in holdings.strip().split("\n") if h.strip()]
    holding_list = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(holding_lines))

    missing_note = ""
    if total_count > ok_count:
        missing_note = (
            f"\n⚠️ 数据缺失：{total_count - ok_count}/{total_count} 支持仓行情获取失败。"
            "涉及这些标的时，必须写明「数据缺失，无法分析」，禁止编造涨跌原因。\n"
        )

    prompt = (
        f"当前时间：{time_desc}\n"
        f"日期：{datetime.now(BEIJING_TZ):%Y年%m月%d日}\n"
        f"用户名：{user.get('name','')}\n\n"
        f"## 大盘指数\n" + "\n".join(index_lines) +
        f"\n\n## 热门板块\n" + "\n".join(sector_lines or ["暂无数据"]) +
        f"\n\n## 用户持仓（共 {total_count} 支）\n{holding_list}\n{missing_note}\n"
        f"请基于以上数据生成一份专业的A股{report_type}报告，要求：\n{focus}\n\n"
        f"⚠️ 重要格式要求：\n"
        f"1. 对以上列出的每个持仓标的，必须单独列一个小标题（### 标的名称），下面写100-150字分析\n"
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
    model = get_model("report")
    print(f"  调用 {model}, prompt {len(prompt)} 字符")

    return _create_with_retry(
        client,
        model=model, max_tokens=8192,
        system=(
            "你是一位专业A股分析师，你的核心职责是对用户的每个持仓标的（股票/基金）进行逐一深度诊断。"
            "你必须遵守以下规则：1) 每个标的必须单独分析，用 ### 标题列出；"
            "2) 不能合并、不能省略、不能只说「整体来看」；3) 每个标的至少写 100 字分析；"
            "4) 数据缺失的标的必须明确说明，禁止编造。"
        ),
        messages=[{"role": "user", "content": prompt}],
    )


# ═══════════════════════════════════════════════
# 推送
# ═══════════════════════════════════════════════

import subprocess


def _find_cc_connect():
    """cron 的 PATH 很短，需要显式找回 npm 全局安装的 cc-connect。"""
    env_bin = os.environ.get("CC_CONNECT_BIN", "")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    found = shutil.which("cc-connect")
    if found:
        return found
    for path in (
        os.path.expanduser("~/.npm-global/bin/cc-connect"),
        "/usr/local/bin/cc-connect",
        "/opt/homebrew/bin/cc-connect",
    ):
        if os.path.exists(path):
            return path
    return None


def _push_via_cc_connect(content: str, target: str) -> bool:
    """通过 cc-connect 推送到指定微信会话。"""
    cc = _find_cc_connect()
    if not cc or not target:
        return False
    try:
        result = subprocess.run(
            [cc, "send", "--stdin", "-p", target],
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


def push_to_user(user: dict, title: str, content: str,
                 default_cc_target: str = "") -> bool:
    """
    智能推送：优先微信 Bot（cc-connect），电脑未开机时回退 Server酱。
    不会重复推送。

    cc 会话优先级：用户自己的 cc_target > default_cc_target。
    多用户时 default_cc_target 为空，避免把别人的报告发到同一个会话。
    """
    name = user.get("name", "?")
    cc_target = str(user.get("cc_target", "")).strip() or default_cc_target

    # 先试 cc-connect（电脑开着就能推微信 Bot）
    if cc_target and _push_via_cc_connect(content, cc_target):
        print(f"  ✅ [微信Bot:{cc_target}] 已推送给 {name}")
        return True

    # cc-connect 没运行/未配置目标 → 回退 Server酱
    if cc_target:
        print("  ⚠️ cc-connect 不可用，回退 Server酱...")
    else:
        print("  ℹ️ 未配置 cc_target，直接使用 Server酱")
    if _push_via_serverchan(user, title, content):
        print(f"  ✅ [Server酱] 已推送给 {name}")
        return True

    print("  ❌ 所有推送方式均失败")
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

    # 单用户才允许默认发到 main；多用户必须各自配置 cc_target，
    # 否则所有人的报告都会发进同一个微信会话。
    default_cc_target = (
        os.environ.get("CC_CONNECT_TARGET", "main") if len(users) == 1 else ""
    )

    success = 0
    for user in users:
        try:
            report = generate_report(report_type, user)
            title = f"📊 A股{cn_type}报告 | {now:%m月%d日}"
            if push_to_user(user, title, report,
                            default_cc_target=default_cc_target):
                success += 1
        except Exception as e:
            import traceback
            print(f"❌ 用户 {user.get('name','?')} 报告生成失败:")
            traceback.print_exc()
            tb_lines = traceback.format_exc().strip().splitlines()
            reason = tb_lines[-1] if tb_lines else str(e)
            push_to_user(user, "❌ 报告生成失败", f"```\n{reason[:500]}\n```",
                         default_cc_target=default_cc_target)

    print(f"\n完成: {success}/{len(users)} 个用户推送成功")


if __name__ == "__main__":
    main()
