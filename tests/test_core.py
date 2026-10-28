"""
测试 — 覆盖核心函数与 Agent 逻辑
运行: python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# 将项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════
# 交易日检测
# ═══════════════════════════════════════════════

class TestTradingDay:
    """测试交易日判断逻辑"""

    def test_weekend_return_false(self):
        """周末返回 False"""
        from report_generator import is_trading_day
        mock_now = datetime(2026, 5, 30, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        with patch("report_generator.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            is_trading, reason = is_trading_day()
            assert is_trading is False
            assert "周六" in reason or "周日" in reason

    def test_weekday_with_volume(self):
        """周一有成交量返回 True — 上证指数格式 volume 在 index 8"""
        from report_generator import is_trading_day
        mock_now = datetime(2026, 6, 1, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        mock_response = MagicMock()
        mock_response.text = (
            'var hq_str_sh000001="上证指数,3100,3150,3200.5,0,0,0,0,1000000,0,...";'
        )
        mock_response.encoding = "gbk"

        with patch("report_generator.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch("report_generator.requests.get", return_value=mock_response):
                is_trading, reason = is_trading_day()
                assert is_trading is True

    def test_weekday_no_volume(self):
        """工作日但无成交量（节假日）= 非交易日"""
        from report_generator import is_trading_day
        mock_now = datetime(2026, 6, 1, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        mock_response = MagicMock()
        mock_response.text = 'var hq_str_sh000001="上证指数,0,0,3200.5,0,0,0,0,0,0,...";'
        mock_response.encoding = "gbk"

        with patch("report_generator.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch("report_generator.requests.get", return_value=mock_response):
                is_trading, reason = is_trading_day()
                assert is_trading is False


    def test_network_error_does_not_skip_silently(self):
        """网络异常不能当成休市，否则会漏报一整天"""
        from report_generator import is_trading_day
        mock_now = datetime(2026, 6, 1, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        with patch("report_generator.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch("report_generator.requests.get", side_effect=Exception("timeout")):
                is_trading, reason = is_trading_day()
        assert is_trading is True
        assert "无法确认" in reason


# ═══════════════════════════════════════════════
# 行情数据
# ═══════════════════════════════════════════════

class TestMarketData:
    """测试行情数据获取"""

    def test_get_market_indices(self):
        """解析新浪指数数据 — 格式: name,open,prev_close,price,high,low,?,?,volume,amount"""
        from report_generator import get_market_indices
        mock_response = MagicMock()
        mock_response.text = (
            'var hq_str_sh000001='
            '"上证指数,3190.00,3200.00,3199.50,3210.50,3180.00,0,0,1000000,500000,'
            '0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0";'
        )
        mock_response.encoding = "gbk"

        with patch("report_generator.requests.Session.get", return_value=mock_response):
            results = get_market_indices()
            assert "上证指数" in results
            assert results["上证指数"]["price"] == 3199.50
            assert results["上证指数"]["high"] == 3210.50
            assert results["上证指数"]["volume"] == 1000000

    def test_get_hot_sectors(self):
        """解析东方财富板块数据"""
        from report_generator import get_hot_sectors
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "diff": [
                    {"f14": "半导体", "f3": 3.5},
                    {"f14": "白酒", "f3": -1.2},
                ]
            }
        }
        with patch("report_generator.requests.get", return_value=mock_response):
            sectors = get_hot_sectors()
            assert len(sectors) == 2
            assert sectors[0]["name"] == "半导体"
            assert sectors[0]["change_pct"] == 3.5

    def test_get_market_indices_network_error(self):
        """网络错误时返回 error 字段"""
        from report_generator import get_market_indices
        with patch("report_generator.requests.Session.get", side_effect=Exception("timeout")):
            results = get_market_indices()
            for name in ["上证指数", "深证成指"]:
                assert "error" in results.get(name, {})


# ═══════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════

class TestReportGeneration:
    """测试报告生成逻辑"""

    def test_generate_report_morning_structure(self):
        """早盘报告包含必需字段"""
        from report_generator import generate_report

        mock_indices = {
            "上证指数": {"name": "上证指数", "price": 3200.0, "change_pct": 0.5,
                         "high": 3220.0, "low": 3180.0},
        }
        mock_sectors = [{"name": "半导体", "change_pct": 3.0}]
        mock_holdings = "测试基金(000001): 净值1.5, 估算1.52 (+1.33%)"

        mock_response = MagicMock()
        mock_response.content = [type("TextBlock", (), {"type": "text", "text": "## 分析报告\n测试内容"})()]

        with patch("report_generator.get_market_indices", return_value=mock_indices), \
             patch("report_generator.get_hot_sectors", return_value=mock_sectors), \
             patch("report_generator.get_holdings_for_user", return_value=(mock_holdings, 1, 1)), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            with patch("report_generator.anthropic.Anthropic") as mock_client:
                mock_client.return_value.messages.create.return_value = mock_response
                report = generate_report("morning", {"name": "测试用户"})
                assert "分析报告" in report
                assert "测试内容" in report


# ═══════════════════════════════════════════════
# 配置 / 模型名
# ═══════════════════════════════════════════════

class TestConfig:
    """测试集中式配置：模型名统一从 config.json 读取"""

    def test_get_model(self):
        from config_loader import get_model
        assert get_model("fast") == "deepseek-v4-flash"
        assert get_model("pro") == "deepseek-v4-pro"
        assert get_model("report") == "deepseek-v4-flash"
        assert get_model("vision") == "deepseek-flash"

    def test_get_model_unknown_fallback(self):
        from config_loader import get_model
        assert get_model("unknown_kind") == "deepseek-v4-flash"


# ═══════════════════════════════════════════════
# 工具执行器
# ═══════════════════════════════════════════════

class TestExecuteTool:
    """测试 execute_tool（mock 数据层，不发起真实请求）"""

    def test_search_stock(self):
        from agent import execute_tool
        with patch("agent.api_search_stock", return_value=[{"code": "300750", "name": "宁德时代"}]):
            out = execute_tool("search_stock", {"keyword": "宁德"})
        assert "300750" in out
        assert "宁德时代" in out

    def test_get_stock_quote(self):
        from agent import execute_tool
        quote = {
            "name": "贵州茅台", "code": "600519", "price": 1500.0,
            "open": 1490.0, "high": 1510.0, "low": 1480.0, "prev_close": 1495.0,
            "volume_hands": 1000, "amount": 150000000.0, "turnover_rate": 0.5,
            "market_cap": 1.8e12, "change_amount": 5.0, "change_pct": 0.33,
        }
        with patch("agent.api_stock_quote", return_value=quote):
            out = execute_tool("get_stock_quote", {"stock_code": "600519"})
        assert "贵州茅台" in out
        assert "600519" in out

    def test_get_stock_quote_not_found(self):
        from agent import execute_tool
        with patch("agent.api_stock_quote", return_value=None):
            out = execute_tool("get_stock_quote", {"stock_code": "999999"})
        assert "未获取到" in out

    def test_get_fund_info(self):
        from agent import execute_tool
        fund = {
            "name": "招商中证白酒", "code": "161725", "type": "指数型",
            "company": "招商基金", "manager": "侯昊", "min_subscribe": 10,
            "is_buyable": True,
        }
        with patch("agent.api_fund_info", return_value=fund):
            out = execute_tool("get_fund_info", {"fund_code": "161725"})
        assert "招商中证白酒" in out
        assert "161725" in out

    def test_unknown_tool(self):
        from agent import execute_tool
        assert execute_tool("does_not_exist", {}) == "未知工具"


# ═══════════════════════════════════════════════
# Agent 循环
# ═══════════════════════════════════════════════

class TestRunAgent:
    """测试 run_agent 循环（mock Anthropic 客户端）"""

    def _text_block(self, text):
        return type("TextBlock", (), {"type": "text", "text": text})()

    def _tool_block(self, name, input_, id_):
        return type("ToolBlock", (), {"type": "tool_use", "name": name, "input": input_, "id": id_})()

    def test_single_tool_then_answer(self):
        """第一轮调用工具，第二轮给出最终回答"""
        from agent import run_agent
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            MagicMock(content=[self._tool_block("get_stock_quote", {"stock_code": "600519"}, "tool_1")]),
            MagicMock(content=[self._text_block("## 分析报告\n茅台行情良好")]),
        ]
        status = MagicMock()
        with patch("agent.get_api_key", return_value="sk-test"), \
             patch("agent.anthropic.Anthropic", return_value=mock_client), \
             patch("agent.execute_tool", return_value="贵州茅台(600519): ¥1500"):
            result = run_agent("分析贵州茅台", status)

        assert "茅台" in result
        assert mock_client.messages.create.call_count == 2
        status.code.assert_called()

    def test_no_api_key(self):
        """未配置 API Key 时直接返回提示"""
        from agent import run_agent
        with patch("agent.get_api_key", return_value=""):
            result = run_agent("分析贵州茅台", MagicMock())
        assert "未配置 API Key" in result


# ═══════════════════════════════════════════════
# 数据层
# ═══════════════════════════════════════════════

class TestSheetsDB:
    """测试 Google Sheets 数据层"""

    def test_load_users_fallback_to_local(self):
        """Google Sheets 不可用时回退到本地文件"""
        import sheets_db
        if not os.path.isdir(os.path.join(os.path.dirname(__file__), "..", "users")):
            pytest.skip("本地 users 目录不存在")
        with patch("sheets_db._get_sheet", side_effect=Exception("network error")):
            users = sheets_db.load_all_users()
            assert isinstance(users, list)

    def test_load_users_grouping(self):
        """多行数据按用户名正确分组"""
        import sheets_db
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = [
            {"name": "张三", "code": "161725", "item_name": "白酒", "type": "fund",
             "alert_change_pct": 3, "alert_nav_below": 0, "cc_target": "alice"},
            {"name": "张三", "code": "000218", "item_name": "黄金", "type": "fund",
             "alert_change_pct": 3, "alert_nav_below": 0},
            {"name": "李四", "code": "600519", "item_name": "茅台", "type": "stock",
             "alert_change_pct": 5, "alert_nav_below": 1200},
        ]
        with patch("sheets_db._get_sheet", return_value=mock_sheet):
            users = sheets_db.load_all_users()
            assert len(users) == 2
            zs = next(u for u in users if u["name"] == "张三")
            assert len(zs["watchlist"]["funds"]) == 2
            assert zs["cc_target"] == "alice"
            ls = next(u for u in users if u["name"] == "李四")
            assert len(ls["watchlist"]["stocks"]) == 1


    def test_load_users_reads_sendkey_and_dedupes(self):
        """重复导入同代码只保留一条，并读取 sendkey"""
        import sheets_db
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = [
            {"name": "王五", "code": "000218", "item_name": "黄金",
             "type": "fund", "sendkey": "SCT1"},
            {"name": "王五", "code": "000218", "item_name": "黄金",
             "type": "fund", "sendkey": "SCT1"},
        ]
        with patch("sheets_db._get_sheet", return_value=mock_sheet):
            users = sheets_db.load_all_users()
        assert len(users) == 1
        assert users[0]["sendkey"] == "SCT1"
        assert len(users[0]["watchlist"]["funds"]) == 1

    def test_add_user_holdings_extends_headers_and_writes_sendkey(self):
        """旧 6 列表格自动补 G/H 表头，并写入 sendkey"""
        import sheets_db
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [[
            "name", "code", "item_name", "type",
            "alert_change_pct", "alert_nav_below",
        ]]
        with patch("sheets_db._get_sheet", return_value=mock_sheet):
            sheets_db.add_user_holdings(
                "张三",
                [{"code": "000218", "name": "黄金"}],
                [],
                sendkey="SCT1",
            )
        mock_sheet.update.assert_called_once_with(
            "G1:H1", [["sendkey", "cc_target"]]
        )
        row = mock_sheet.append_rows.call_args.args[0][0]
        assert len(row) == 8
        assert row[1] == "'000218"
        assert row[6] == "SCT1"

    def test_ensure_headers_on_empty_sheet(self):
        import sheets_db
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = []
        with patch("sheets_db._get_sheet", return_value=mock_sheet):
            sheets_db.ensure_headers()
        mock_sheet.update.assert_called_once_with(
            "A1:H1", [sheets_db.SHEET_HEADERS]
        )


# ═══════════════════════════════════════════════
# 数据接口修复：基金估值换源 / 详情 JSON / 板块 Referer
# ═══════════════════════════════════════════════

class TestFundDataFixes:
    def _resp(self, payload):
        resp = MagicMock()
        resp.json.return_value = payload
        resp.text = json.dumps(payload, ensure_ascii=False)
        return resp

    def test_fund_valuation_without_estimate(self):
        """GSZ 为空时退回最新净值，并标记 is_estimate=False"""
        from data_api import api_fund_valuation
        payload = {"Datas": [{
            "FCODE": "000218", "SHORTNAME": "国泰黄金ETF联接A",
            "PDATE": "2026-10-26", "NAV": "3.1049", "NAVCHGRT": "-0.32",
            "GSZ": None, "GSZZL": None, "GZTIME": None,
        }]}
        with patch("data_api.SESSION.get", return_value=self._resp(payload)):
            val = api_fund_valuation("000218")
        assert val["name"] == "国泰黄金ETF联接A"
        assert val["nav"] == 3.1049
        assert val["is_estimate"] is False
        assert val["estimated_nav"] == 3.1049
        assert val["estimated_change_pct"] == -0.32

    def test_fund_valuation_with_estimate(self):
        """有 GSZ/GSZZL 时按实时估值返回"""
        from data_api import api_fund_valuation
        payload = {"Datas": [{
            "FCODE": "161725", "SHORTNAME": "招商中证白酒",
            "PDATE": "2026-10-26", "NAV": "0.5459", "NAVCHGRT": "2.13",
            "GSZ": "0.5600", "GSZZL": "2.58", "GZTIME": "2026-10-27 10:00",
        }]}
        with patch("data_api.SESSION.get", return_value=self._resp(payload)):
            val = api_fund_valuation("161725")
        assert val["is_estimate"] is True
        assert val["estimated_nav"] == 0.56
        assert val["estimated_change_pct"] == 2.58

    def test_fund_valuation_fallback_to_nav_history(self):
        """主接口失败时退回净值历史，并用基金详情补名称"""
        from data_api import api_fund_valuation
        with patch("data_api.SESSION.get", side_effect=Exception("blocked")), \
             patch("data_api.api_fund_nav_history", return_value=[{
                 "date": "2026-10-26", "nav": 3.1049, "acc_nav": 3.1049,
                 "daily_change_pct": -0.32,
             }]), \
             patch("data_api.api_fund_info", return_value={"name": "国泰黄金ETF联接A"}):
            val = api_fund_valuation("000218")
        assert val["is_estimate"] is False
        assert val["name"] == "国泰黄金ETF联接A"
        assert val["nav"] == 3.1049

    def test_fund_info_plain_json(self):
        """接口返回纯 JSON（非 JSONP）时也能解析"""
        from data_api import api_fund_info
        payload = {"Datas": [{"FundBaseInfo": {
            "FCODE": "000218", "SHORTNAME": "国泰黄金ETF联接A",
            "FTYPE": "指数型-其他", "JJGS": "国泰基金", "JJJL": "艾小军",
            "MINSG": 10, "ISBUY": "1",
        }}]}
        resp = MagicMock()
        resp.text = json.dumps(payload, ensure_ascii=False)
        with patch("data_api.SESSION.get", return_value=resp):
            info = api_fund_info("000218")
        assert info["code"] == "000218"
        assert info["manager"] == "艾小军"
        assert info["is_buyable"] is True

    def test_hot_sectors_sends_referer(self):
        """板块接口必须带 quote 站 Referer，否则会空响应"""
        from report_generator import get_hot_sectors
        resp = MagicMock()
        resp.json.return_value = {"data": {"diff": [{"f14": "半导体", "f3": 3.5}]}}
        with patch("report_generator.requests.get", return_value=resp) as mock_get:
            sectors = get_hot_sectors()
        assert sectors == [{"name": "半导体", "change_pct": 3.5}]
        assert mock_get.call_args.kwargs["headers"]["Referer"] == "https://quote.eastmoney.com/"
        assert mock_get.call_args.kwargs["params"]["ut"]

    def test_get_holdings_returns_counts(self):
        """持仓取数返回 (文本, 成功数, 总数)，并标注无实时估值"""
        from report_generator import get_holdings_for_user
        user = {"watchlist": {
            "stocks": [{"code": "600519", "name": "贵州茅台"}],
            "funds": [{"code": "000218", "name": "国泰黄金"}],
        }}
        quote = {
            "name": "贵州茅台", "price": 1500.0, "high": 1510.0, "low": 1490.0,
            "change_pct": 0.5,
        }
        val = {
            "name": "国泰黄金ETF联接A", "nav": 3.1049,
            "estimated_nav": 3.1049, "estimated_change_pct": -0.32,
            "is_estimate": False,
        }
        with patch("report_generator.api_stock_quote", return_value=quote), \
             patch("report_generator.api_fund_valuation", return_value=val):
            text, ok, total = get_holdings_for_user(user)
        assert (ok, total) == (2, 2)
        assert "600519" in text and "000218" in text
        assert "无实时估值" in text


# ═══════════════════════════════════════════════
# 报告熔断 & thinking 重试
# ═══════════════════════════════════════════════

class TestReportGuard:
    def test_all_holdings_failed_raises(self):
        """全部持仓取数失败时终止，不调用模型"""
        from report_generator import generate_report
        indices = {"上证指数": {"price": 3000, "change_pct": 0.1,
                                "high": 3010, "low": 2990}}
        with patch("report_generator.get_market_indices", return_value=indices), \
             patch("report_generator.get_hot_sectors", return_value=[]), \
             patch("report_generator.get_holdings_for_user",
                   return_value=("某基金(000001): 获取失败", 0, 1)), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            with pytest.raises(RuntimeError, match="全部获取失败"):
                generate_report("morning", {"name": "测试用户"})


class TestModelRetry:
    def _block(self, block_type, text=""):
        return type("Block", (), {"type": block_type, "text": text})()

    def test_retry_after_thinking_only(self):
        """第一次只有 thinking，第二次有 text → 自动重试成功"""
        from report_generator import _create_with_retry
        client = MagicMock()
        client.messages.create.side_effect = [
            MagicMock(content=[self._block("thinking")]),
            MagicMock(content=[self._block("text", "最终报告")]),
        ]
        result = _create_with_retry(
            client, model="m", max_tokens=10, system="s", messages=[],
        )
        assert result == "最终报告"
        assert client.messages.create.call_count == 2

    def test_agent_thinking_only_returns_hint(self):
        """Web 端遇到 thinking-only 时返回可读提示而不是 AttributeError"""
        from agent import run_agent
        client = MagicMock()
        client.messages.create.return_value = MagicMock(
            content=[self._block("thinking")]
        )
        with patch("agent.get_api_key", return_value="sk-test"), \
             patch("agent.anthropic.Anthropic", return_value=client):
            result = run_agent("分析贵州茅台", MagicMock())
        assert "未返回文本内容" in result


# ═══════════════════════════════════════════════
# 推送路由：多用户不再广播到同一个微信会话
# ═══════════════════════════════════════════════

class TestPushRouting:
    def test_cc_connect_uses_given_target(self):
        import report_generator as rg
        with patch.object(rg, "_find_cc_connect", return_value="/usr/bin/cc-connect"), \
             patch.object(rg.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 0
            ok = rg._push_via_cc_connect("hello", "alice")
        assert ok is True
        assert mock_run.call_args.args[0] == [
            "/usr/bin/cc-connect", "send", "--stdin", "-p", "alice",
        ]

    def test_multi_user_without_target_skips_cc(self):
        """多用户且未配置 cc_target 时只走 Server酱，避免发错人"""
        import report_generator as rg
        with patch.object(rg, "_push_via_cc_connect") as mock_cc, \
             patch.object(rg, "_push_via_serverchan", return_value=True) as mock_sc:
            ok = rg.push_to_user({"name": "张三"}, "t", "c", default_cc_target="")
        assert ok is True
        mock_cc.assert_not_called()
        mock_sc.assert_called_once()

    def test_user_target_overrides_default(self):
        import report_generator as rg
        with patch.object(rg, "_push_via_cc_connect", return_value=True) as mock_cc:
            rg.push_to_user(
                {"name": "张三", "cc_target": "alice"}, "t", "c",
                default_cc_target="main",
            )
        mock_cc.assert_called_once_with("c", "alice")


    def test_main_multi_user_does_not_default_to_main(self):
        """多用户主流程：default_cc_target 必须为空"""
        import report_generator as rg
        users = [{"name": "A"}, {"name": "B"}]
        with patch.object(rg, "is_trading_day", return_value=(True, "")), \
             patch.object(rg, "load_all_users", return_value=users), \
             patch.object(rg, "generate_report", return_value="r"), \
             patch.object(rg, "push_to_user", return_value=True) as mock_push, \
             patch.object(rg.sys, "argv", ["report_generator.py", "morning"]):
            rg.main()
        assert mock_push.call_count == 2
        for call in mock_push.call_args_list:
            assert call.kwargs["default_cc_target"] == ""

    def test_main_single_user_defaults_to_main(self):
        """单用户主流程：允许默认发到 main"""
        import report_generator as rg
        with patch.object(rg, "is_trading_day", return_value=(True, "")), \
             patch.object(rg, "load_all_users", return_value=[{"name": "A"}]), \
             patch.object(rg, "generate_report", return_value="r"), \
             patch.object(rg, "push_to_user", return_value=True) as mock_push, \
             patch.dict(os.environ, {"CC_CONNECT_TARGET": "main"}), \
             patch.object(rg.sys, "argv", ["report_generator.py", "morning"]):
            rg.main()
        assert mock_push.call_args.kwargs["default_cc_target"] == "main"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
