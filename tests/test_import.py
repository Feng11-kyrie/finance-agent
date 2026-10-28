"""持仓文件导入测试。"""

import io

import pandas as pd
import pytest

import holdings_import as hi


def test_parse_template_csv():
    rows, errors, mapping = hi.parse_holdings(
        hi.read_table(hi.CSV_TEMPLATE.encode("utf-8"), "template.csv")
    )
    assert errors == []
    assert mapping["code"] == "代码"
    assert rows[0] == {
        "type": "fund", "code": "000218", "name": "国泰黄金ETF联接A",
        "buy_nav": 3.1049, "amount": 10000.0,
    }
    assert rows[1] == {
        "type": "stock", "code": "600519", "name": "贵州茅台",
        "buy_price": 1500.0, "shares": 100,
    }


def test_parse_gbk_broker_csv():
    """券商导出常见 GBK 编码 + 证券代码/成本价/持仓数量列名"""
    data = "证券代码,证券名称,持仓数量,成本价\n600519,贵州茅台,100,1500\n".encode("gbk")
    rows, errors, _ = hi.parse_holdings(hi.read_table(data, "broker.csv"))
    assert errors == []
    assert rows == [{
        "type": "stock", "code": "600519", "name": "贵州茅台",
        "buy_price": 1500.0, "shares": 100,
    }]


def test_fund_shares_fallback_to_amount():
    """基金没有金额列时，用 份额 × 净值 估算投入金额"""
    data = "基金代码,基金名称,持有份额,持仓成本\n218,国泰黄金,1000,3.1\n".encode("utf-8")
    rows, errors, _ = hi.parse_holdings(hi.read_table(data, "fund.csv"))
    assert errors == []
    assert rows[0]["type"] == "fund"
    assert rows[0]["code"] == "000218"
    assert rows[0]["amount"] == pytest.approx(3100.0)


def test_parse_xlsx():
    df = pd.DataFrame([{
        "类型": "基金", "代码": 218, "名称": "国泰黄金",
        "买入价": 3.1, "金额": 10000,
    }])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    rows, errors, _ = hi.parse_holdings(hi.read_table(buffer.getvalue(), "h.xlsx"))
    assert errors == []
    assert rows[0]["code"] == "000218"
    assert rows[0]["amount"] == 10000.0


def test_missing_code_column_raises():
    df = pd.DataFrame([{"名称": "贵州茅台", "成本价": 1500}])
    with pytest.raises(ValueError, match="代码列"):
        hi.parse_holdings(df)


def test_invalid_rows_are_reported_and_skipped():
    data = (
        "类型,代码,名称,买入价,数量,金额\n"
        "股票,,茅台,1500,100,\n"
        "基金,000218,黄金,0,,\n"
        "股票,300750,宁德时代,180,200,\n"
    )
    rows, errors, _ = hi.parse_holdings(
        hi.read_table(data.encode("utf-8"), "bad.csv")
    )
    assert len(rows) == 1
    assert rows[0]["code"] == "300750"
    assert len(errors) == 2


def test_merge_adds_and_updates():
    current = {
        "stocks": [{"code": "600519", "name": "贵州茅台", "buy_price": 1400, "shares": 100}],
        "funds": [],
    }
    rows = [
        {"type": "stock", "code": "600519", "name": "贵州茅台",
         "buy_price": 1500, "shares": 200},
        {"type": "fund", "code": "000218", "name": "国泰黄金",
         "buy_nav": 3.1, "amount": 10000},
    ]
    merged, added, updated = hi.merge_holdings(current, rows)
    assert (added, updated) == (1, 1)
    assert merged["stocks"][0]["buy_price"] == 1500
    assert merged["stocks"][0]["shares"] == 200
    assert merged["funds"][0]["code"] == "000218"


def test_to_sheet_payload():
    holdings = {
        "stocks": [{"code": "600519", "name": "贵州茅台"}],
        "funds": [{"code": "000218", "name": "国泰黄金"}],
    }
    funds, stocks = hi.to_sheet_payload(holdings)
    assert funds[0]["code"] == "000218"
    assert funds[0]["alert_change_pct"] == 3
    assert stocks[0]["alert_change_pct"] == 5
