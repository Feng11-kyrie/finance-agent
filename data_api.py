"""数据 API 层 - 新浪财经 / 东方财富 / 天天基金行情数据获取。

只负责请求与解析，不依赖 Streamlit，可单独测试。
"""
from __future__ import annotations

import json
import re

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.eastmoney.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# 基金接口需要基金站 Referer，否则部分接口会返回空响应
FUND_HEADERS = {
    **HEADERS,
    "Referer": "https://fund.eastmoney.com/",
}

# 基金移动接口对桌面 Chrome UA 会返回“网络繁忙”，需用移动端 UA
FUND_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://fund.eastmoney.com/",
}


def _parse_json_or_jsonp(text: str):
    """兼容纯 JSON 与 JSONP（jsonpgz(...) / callback(...)）两种返回格式。"""
    text = text.strip()
    if not text:
        return None
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\((.+)\)", text, re.S)
    if match:
        return json.loads(match.group(1))
    return None


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
        data = _parse_json_or_jsonp(r.text)
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
    """获取基金净值与实时估值。

    主源：东财基金移动接口（仍可用，返回最新净值 NAV/日涨跌 NAVCHGRT）。
    原来使用的 fundgz.1234567.com.cn 已下线（返回 404 页面），因此这里改为
    「有实时估值就用 GSZ/GSZZL，没有就退回最近净值」，并通过 is_estimate
    告诉调用方当前数字是不是实时估算，避免把昨日涨跌当成今日估算。
    兜底：净值历史接口（api_fund_nav_history）。
    """
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    params = {
        "pageIndex": 1, "pageSize": 1,
        "plat": "Android", "appType": "ttjj",
        "product": "EFund", "Version": "1",
        "deviceid": "1", "Fcodes": code,
    }
    try:
        r = SESSION.get(url, params=params, headers=FUND_MOBILE_HEADERS, timeout=8)
        items = (r.json() or {}).get("Datas") or []
        if items:
            d = items[0]
            nav = float(d.get("NAV") or 0)
            if nav > 0:
                gsz = d.get("GSZ")
                gszzl = d.get("GSZZL")
                is_estimate = gsz not in (None, "", 0) and gszzl not in (None, "")
                return {
                    "code": d.get("FCODE", code),
                    "name": d.get("SHORTNAME", ""),
                    "nav_date": d.get("PDATE", ""),
                    "nav": nav,
                    "estimated_nav": float(gsz) if is_estimate else nav,
                    "estimated_change_pct": (
                        float(gszzl) if is_estimate else float(d.get("NAVCHGRT") or 0)
                    ),
                    "estimate_time": d.get("GZTIME") or d.get("PDATE", ""),
                    "is_estimate": is_estimate,
                }
    except Exception:
        pass

    # 兜底：最近一条净值（无实时估值）
    try:
        history = api_fund_nav_history(code, 1)
        if history:
            h = history[0]
            name = ""
            try:
                info = api_fund_info(code)
                if info:
                    name = info.get("name", "")
            except Exception:
                pass
            return {
                "code": code,
                "name": name,
                "nav_date": h["date"],
                "nav": h["nav"],
                "estimated_nav": h["nav"],
                "estimated_change_pct": h["daily_change_pct"],
                "estimate_time": h["date"],
                "is_estimate": False,
            }
    except Exception:
        pass

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
    """获取基金基本信息（基金公司、经理、起购金额等）"""
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    params = {"m": "1", "key": code}
    try:
        r = SESSION.get(url, params=params, timeout=8)
        # 该接口返回纯 JSON；旧代码只按 JSONP 解析，导致永远返回 None
        data = _parse_json_or_jsonp(r.text)
        if not data:
            return None
        for item in data.get("Datas", []):
            info = item.get("FundBaseInfo") or {}
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
        # 兼容扁平结构（部分返回不再包 FundBaseInfo）
        for item in data.get("Datas", []):
            if item.get("CODE") == code:
                return {
                    "code": item.get("CODE", code),
                    "name": item.get("NAME", ""),
                    "type": item.get("CATEGORYDESC", ""),
                    "company": item.get("JJGS", ""),
                    "manager": item.get("JJJL", ""),
                    "min_subscribe": item.get("MINSG", 0),
                    "is_buyable": item.get("ISBUY", "") == "1",
                }
        return None
    except Exception:
        return None
