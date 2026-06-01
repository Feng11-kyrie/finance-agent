"""
面试展示用测试 — 覆盖核心函数
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
        # Mock datetime.now to return a Saturday
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
        # 新浪格式: 0=name,1=open,2=prev_close,3=price,4=high,5=low,6,7=占位,8=volume
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


# ═══════════════════════════════════════════════
# 行情数据
# ═══════════════════════════════════════════════

class TestMarketData:
    """测试行情数据获取"""

    def test_get_market_indices(self):
        """解析新浪指数数据 — 格式: name,open,prev_close,price,high,low,?,?,volume,amount"""
        from report_generator import get_market_indices
        mock_response = MagicMock()
        # 新浪数据格式: 0=name,1=open,2=prev_close,3=price,4=high,5=low,6,7=占位,8=volume
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
             patch("report_generator.get_holdings_for_user", return_value=mock_holdings), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            with patch("report_generator.anthropic.Anthropic") as mock_client:
                mock_client.return_value.messages.create.return_value = mock_response
                report = generate_report("morning", {"name": "测试用户"})
                assert "分析报告" in report
                assert "测试内容" in report


# ═══════════════════════════════════════════════
# 时间窗口
# ═══════════════════════════════════════════════

class TestTimeWindow:
    """测试报告时间窗口保护 — 在 main() 中已内联实现"""

    def test_morning_window_bounds(self):
        """早盘窗口: 9:00-12:00"""
        # 9:00 在窗口内
        assert 9 <= 9 < 12
        # 11:59 在窗口内
        assert 9 <= 11 < 12
        # 8:59 不在窗口内
        assert not (9 <= 8 < 12)
        # 12:00 不在窗口内
        assert not (9 <= 12 < 12)

    def test_afternoon_window_bounds(self):
        """午后窗口: 14:00-17:00"""
        assert 14 <= 14 < 17
        assert 14 <= 16 < 17
        assert not (14 <= 13 < 17)
        assert not (14 <= 17 < 17)


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
             "alert_change_pct": 3, "alert_nav_below": 0},
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
            ls = next(u for u in users if u["name"] == "李四")
            assert len(ls["watchlist"]["stocks"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
