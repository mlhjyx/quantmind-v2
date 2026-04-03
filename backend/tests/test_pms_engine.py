"""PMS Engine 单元测试。"""

from app.services.pms_engine import PMSEngine, PMSLevel, check_protection

# ── 阶梯保护规则测试 ──


class TestCheckProtection:
    """check_protection 纯函数测试。"""

    LEVELS = [
        PMSLevel(1, 0.30, 0.15),
        PMSLevel(2, 0.20, 0.12),
        PMSLevel(3, 0.10, 0.10),
    ]

    def test_level1_trigger(self):
        """浮盈35%回撤18% → 触发层级1。"""
        # entry=10, peak=15.4, current=12.6
        # pnl = (12.6-10)/10 = 26% ... 不够
        # 调整: entry=10, peak=16, current=13.5
        # pnl = 35%, dd = (16-13.5)/16 = 15.6%
        result = check_protection(10.0, 16.0, 13.5, self.LEVELS)
        assert result == 1

    def test_level2_trigger(self):
        """浮盈22%回撤13% → 触发层级2。"""
        # entry=10, peak=14.0, current=12.2
        # pnl = 22%, dd = (14-12.2)/14 = 12.9%
        result = check_protection(10.0, 14.0, 12.2, self.LEVELS)
        assert result == 2

    def test_level3_trigger(self):
        """浮盈12%回撤11% → 触发层级3。"""
        # entry=10, peak=12.6, current=11.2
        # pnl = 12%, dd = (12.6-11.2)/12.6 = 11.1%
        result = check_protection(10.0, 12.6, 11.2, self.LEVELS)
        assert result == 3

    def test_no_trigger_low_drawdown(self):
        """浮盈25%回撤5% → 不触发（回撤不够）。"""
        # entry=10, peak=13.2, current=12.5
        # pnl = 25%, dd = (13.2-12.5)/13.2 = 5.3%
        result = check_protection(10.0, 13.2, 12.5, self.LEVELS)
        assert result is None

    def test_no_trigger_low_gain(self):
        """浮盈5%回撤20% → 不触发（浮盈不够）。"""
        # entry=10, peak=13.1, current=10.5
        # pnl = 5%, dd = (13.1-10.5)/13.1 = 19.8%
        result = check_protection(10.0, 13.1, 10.5, self.LEVELS)
        assert result is None

    def test_no_trigger_loss(self):
        """亏损状态 → 不触发。"""
        result = check_protection(10.0, 10.0, 8.0, self.LEVELS)
        assert result is None

    def test_invalid_prices(self):
        """无效价格 → 不触发。"""
        assert check_protection(0, 10.0, 8.0, self.LEVELS) is None
        assert check_protection(10.0, 0, 8.0, self.LEVELS) is None
        assert check_protection(10.0, 10.0, 0, self.LEVELS) is None

    def test_level1_priority_over_level2(self):
        """同时满足层级1和2，返回层级1（优先级高）。"""
        # entry=10, peak=20, current=14
        # pnl = 40%, dd = (20-14)/20 = 30%
        result = check_protection(10.0, 20.0, 14.0, self.LEVELS)
        assert result == 1

    def test_exact_threshold(self):
        """恰好等于阈值边界 → 触发。"""
        # entry=10, peak=14.3, current=13.0
        # pnl = (13-10)/10 = 30%, dd = (14.3-13)/14.3 = 9.09% → 不够层级1
        # 精确计算: need dd >= 15%
        # entry=10, peak=15.3, current=13.0
        # pnl = 30%, dd = (15.3-13)/15.3 = 15.03%
        result = check_protection(10.0, 15.3, 13.0, self.LEVELS)
        assert result == 1


# ── check_all_positions 测试 ──


class TestCheckAllPositions:
    """PMSEngine.check_all_positions 测试。"""

    def test_mixed_portfolio(self):
        """组合中有触发和未触发的股票。"""
        engine = PMSEngine()
        positions = [
            {"code": "000001.SZ", "entry_price": 10.0, "shares": 1000},
            {"code": "600519.SH", "entry_price": 1500.0, "shares": 100},
            {"code": "000002.SZ", "entry_price": 20.0, "shares": 500},
        ]
        peaks = {
            "000001.SZ": 16.0,  # high peak
            "600519.SH": 1600.0,  # moderate peak
            "000002.SZ": 21.0,  # low peak
        }
        currents = {
            "000001.SZ": 13.5,  # pnl=35%, dd=15.6% → Level 1
            "600519.SH": 1550.0,  # pnl=3.3%, dd=3.1% → No trigger
            "000002.SZ": 20.5,  # pnl=2.5%, dd=2.4% → No trigger
        }

        signals = engine.check_all_positions(positions, peaks, currents)
        assert len(signals) == 1
        assert signals[0].code == "000001.SZ"
        assert signals[0].level == 1

    def test_missing_price_skipped(self):
        """无当前价格的股票跳过。"""
        engine = PMSEngine()
        positions = [{"code": "000001.SZ", "entry_price": 10.0, "shares": 1000}]
        signals = engine.check_all_positions(positions, {"000001.SZ": 15.0}, {})
        assert len(signals) == 0

    def test_empty_positions(self):
        """空持仓返回空列表。"""
        engine = PMSEngine()
        assert engine.check_all_positions([], {}, {}) == []


# ── build_monitor_data 测试 ──


class TestBuildMonitorData:
    """PMSEngine.build_monitor_data 测试。"""

    def test_monitor_data_format(self):
        """监控数据包含所有必需字段。"""
        engine = PMSEngine()
        positions = [{"code": "000001.SZ", "entry_price": 10.0, "shares": 1000}]
        data = engine.build_monitor_data(
            positions,
            {"000001.SZ": 14.0},
            {"000001.SZ": 13.0},
        )
        assert len(data) == 1
        d = data[0]
        assert d["code"] == "000001.SZ"
        assert d["entry_price"] == 10.0
        assert d["current_price"] == 13.0
        assert d["peak_price"] == 14.0
        assert "unrealized_pnl_pct" in d
        assert "drawdown_from_peak_pct" in d
        assert "status" in d

    def test_config_from_env(self):
        """PMS配置从settings正确加载。"""
        from app.config import settings

        assert settings.PMS_ENABLED is True
        assert settings.PMS_LEVEL1_GAIN == 0.30
        assert settings.PMS_LEVEL1_DRAWDOWN == 0.15
        assert settings.PMS_LEVEL3_GAIN == 0.10
