"""截图识图导入测试（不调用真实视觉 API）。"""

import json

import pandas as pd
from unittest.mock import patch

import pytest

import vision_import as vi


def test_parse_json_payload_with_fence_and_prefix():
    text = '说明：\n```json\n{"items": [{"code": "000218"}]}\n```'
    payload = vi.parse_json_payload(text)
    assert payload["items"][0]["code"] == "000218"


def test_build_fund_from_shares_and_cost():
    payload = {"items": [{
        "type": "fund", "code": "000218", "name": "国泰黄金ETF联接A",
        "shares": 1000, "cost_nav": 3.1, "market_value": 3104.9, "profit": 4.9,
    }]}
    rows, warnings = vi.build_rows(payload)
    assert warnings == []
    assert rows[0] == {
        "type": "fund", "code": "000218", "name": "国泰黄金ETF联接A",
        "buy_nav": 3.1, "amount": 3100.0,
        "market_value": 3104.9, "profit": 4.9, "note": "",
    }


def test_build_fund_back_calculates_cost_from_market_and_profit():
    payload = {"items": [{
        "type": "fund", "code": "161725", "name": "招商中证白酒",
        "shares": 1000, "market_value": 3104.9, "profit": 4.9,
    }]}
    rows, _ = vi.build_rows(payload)
    assert rows[0]["amount"] == pytest.approx(3100.0)
    assert rows[0]["buy_nav"] == pytest.approx(3.1)
    assert "倒推成本" in rows[0]["note"]


def test_build_stock_row():
    payload = {"items": [{
        "type": "stock", "code": "600519", "name": "贵州茅台",
        "shares": 100, "cost_nav": 1500,
    }]}
    rows, warnings = vi.build_rows(payload)
    assert warnings == []
    assert rows[0] == {
        "type": "stock", "code": "600519", "name": "贵州茅台",
        "buy_price": 1500.0, "shares": 100, "note": "",
    }


def test_missing_cost_data_is_skipped_with_warning():
    payload = {"items": [{
        "type": "fund", "code": "000001", "name": "华夏成长", "shares": 100,
    }]}
    rows, warnings = vi.build_rows(payload)
    assert rows == []
    assert warnings and "信息不足" in warnings[0]


def test_type_inference_prefers_fund_name_hint():
    payload = {"items": [
        {"type": "股票型", "code": "000001", "name": "华夏成长混合",
         "shares": 100, "cost_nav": 1.0},
        {"type": "股票", "code": "600519", "name": "贵州茅台",
         "shares": 100, "cost_nav": 1500},
    ]}
    rows, _ = vi.build_rows(payload)
    assert rows[0]["type"] == "fund"
    assert rows[1]["type"] == "stock"


def test_chinese_field_aliases():
    payload = {"items": [{
        "基金代码": "000218", "基金名称": "国泰黄金ETF联接A",
        "持有份额": 1000, "成本净值": 3.1,
    }]}
    rows, _ = vi.build_rows(payload)
    assert rows[0]["code"] == "000218"
    assert rows[0]["amount"] == pytest.approx(3100.0)


def test_recognize_uses_extractor():
    payload = {"items": [{
        "type": "fund", "code": "000218", "name": "国泰黄金",
        "shares": 1000, "cost_nav": 3.1,
    }]}
    with patch("vision_import.extract_holdings", return_value=(payload, "raw")):
        rows, warnings, raw = vi.recognize(b"img", "shot.png", "支付宝", "key")
    assert raw == "raw"
    assert warnings == []
    assert rows[0]["code"] == "000218"


def test_rows_for_editor_shapes():
    rows = [{
        "type": "fund", "code": "000218", "name": "国泰黄金",
        "buy_nav": 3.1, "amount": 3100, "note": "测试",
    }]
    preview = vi.rows_for_editor(rows)
    assert preview[0]["类型"] == "基金"
    assert preview[0]["买入价/净值"] == "3.1000"


def test_media_type_for():
    assert vi.media_type_for("a.PNG") == "image/png"
    assert vi.media_type_for("a.jpeg") == "image/jpeg"
    assert vi.media_type_for("a.unknown") == "image/png"

def test_editor_to_rows_converts_fund_and_stock():
    df = pd.DataFrame([
        {"类型": "基金", "代码": "000218", "名称": "国泰黄金",
         "买入价/净值": 3.1, "份额": None, "金额": 3100, "备注": ""},
        {"类型": "股票", "代码": "600519", "名称": "贵州茅台",
         "买入价/净值": 1500, "份额": 100, "金额": None, "备注": ""},
    ])
    rows, errors = vi.editor_to_rows(df)
    assert errors == []
    assert rows[0]["amount"] == 3100
    assert rows[1]["shares"] == 100


def test_editor_to_rows_rejects_bad_code_and_missing_amount():
    df = pd.DataFrame([
        {"类型": "基金", "代码": "ABCDEF", "名称": "国泰黄金",
         "买入价/净值": 3.1, "份额": None, "金额": 3100, "备注": ""},
        {"类型": "基金", "代码": "000218", "名称": "国泰黄金",
         "买入价/净值": 3.1, "份额": None, "金额": None, "备注": ""},
    ])
    rows, errors = vi.editor_to_rows(df)
    assert rows == []
    assert len(errors) == 2

def test_build_fund_with_only_market_and_profit_is_kept():
    payload = {"items": [{
        "type": "fund", "code": "000218", "name": "国泰黄金",
        "shares": None, "cost_nav": None,
        "market_value": 3104.9, "profit": 4.9,
    }]}
    rows, warnings = vi.build_rows(payload)
    assert warnings == []
    assert rows[0]["buy_nav"] is None
    assert rows[0]["market_value"] == 3104.9
    assert "最新净值" in rows[0]["note"]


def test_enrich_rows_uses_latest_nav():
    rows = [{
        "type": "fund", "code": "000218", "name": "国泰黄金",
        "buy_nav": None, "amount": None,
        "market_value": 3104.9, "profit": 4.9, "note": "",
    }]
    with patch("vision_import.api_fund_valuation", return_value={"nav": 3.1049}):
        out, warnings = vi.enrich_rows(rows)
    assert warnings == []
    assert out[0]["amount"] == pytest.approx(3100.0)
    assert out[0]["buy_nav"] == pytest.approx(3.1)


def test_editor_to_rows_accepts_market_and_profit():
    df = pd.DataFrame([{
        "类型": "基金", "代码": "000218", "名称": "国泰黄金",
        "买入价/净值": None, "份额": None, "金额": None,
        "当前市值": 3104.9, "收益": 4.9, "备注": "",
    }])
    rows, errors = vi.editor_to_rows(df)
    assert errors == []
    assert rows[0]["buy_nav"] is None
    assert rows[0]["market_value"] == pytest.approx(3104.9)

def test_editor_roundtrip_from_preview_strings():
    rows = [{
        "type": "fund", "code": "000218", "name": "国泰黄金",
        "buy_nav": 3.1, "amount": 3100.0,
        "market_value": 3104.9, "profit": 4.9, "note": "",
    }]
    preview = pd.DataFrame(vi.rows_for_editor(rows))
    converted, errors = vi.editor_to_rows(preview)
    assert errors == []
    assert converted[0]["buy_nav"] == pytest.approx(3.1)
    assert converted[0]["amount"] == pytest.approx(3100.0)

def test_enrich_resolves_missing_code_by_name():
    rows = [{
        "type": "fund", "code": "", "name": "国泰黄金ETF联接A",
        "buy_nav": None, "amount": None,
        "market_value": 3104.9, "profit": 4.9, "note": "缺代码，请补全",
    }]
    with patch("vision_import.api_search_fund",
               return_value=[{"code": "000218", "name": "国泰黄金ETF联接A"}]), \
         patch("vision_import.api_fund_valuation", return_value={"nav": 3.1049}):
        out, warnings = vi.enrich_rows(rows)
    assert warnings == []
    assert out[0]["code"] == "000218"
    assert out[0]["amount"] == pytest.approx(3100.0)
    assert "缺代码" not in out[0]["note"]
