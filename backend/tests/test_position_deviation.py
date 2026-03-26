"""仓位偏差指标测试。

验证calc_position_deviation的三个输出:
- mean_position_deviation: mean(|actual_w - target_w|) * 100
- max_position_deviation: max(|actual_w - target_w|) * 100
- total_cash_drag: (1 - sum(actual_mv) / total_value) * 100
"""

from engines.metrics import calc_position_deviation


class TestCalcPositionDeviation:
    """calc_position_deviation测试。"""

    def test_perfect_match(self) -> None:
        """完美匹配：0偏差。"""
        # 2只股票各50%权重，实际持仓完美匹配
        holdings = {"000001.SZ": 5000, "600519.SH": 500}
        target_weights = {"000001.SZ": 0.50, "600519.SH": 0.50}
        prices = {"000001.SZ": 10.0, "600519.SH": 100.0}
        total_value = 5000 * 10 + 500 * 100  # 100000, 全仓无现金

        result = calc_position_deviation(holdings, target_weights, prices, total_value)

        assert result["mean_position_deviation"] == 0.0
        assert result["max_position_deviation"] == 0.0
        assert result["total_cash_drag"] == 0.0

    def test_lot_constraint_deviation(self) -> None:
        """整手约束偏差：6666股→6600股（100股整手）。

        目标: 100万 * 6.67% = 66700元，股价10元 → 6670股 → 整手6600股
        实际市值: 6600 * 10 = 66000元
        目标市值: 66700元
        偏差 = |66000/total - 0.0667|
        """
        # 15只等权，每只6.67%
        total_value = 1_000_000.0
        target_weight = 1.0 / 15  # 0.06667

        # 模拟整手约束：每只目标6667股，整手后6600股
        holdings = {}
        target_weights = {}
        prices = {}
        for i in range(1, 16):
            code = f"{i:06d}.SZ"
            holdings[code] = 6600  # 整手后
            target_weights[code] = target_weight
            prices[code] = 10.0

        # 实际市值 = 15 * 6600 * 10 = 990000
        # total_value = 1000000 (含10000现金)

        result = calc_position_deviation(holdings, target_weights, prices, total_value)

        # 每只偏差: |6600*10/1000000 - 1/15| = |0.066 - 0.06667| = 0.00067
        expected_dev_per_stock = abs(6600 * 10.0 / total_value - target_weight)
        expected_mean = expected_dev_per_stock * 100  # 所有15只偏差相同

        assert abs(result["mean_position_deviation"] - expected_mean) < 0.01
        assert abs(result["max_position_deviation"] - expected_mean) < 0.01

        # 现金拖累 = (1 - 990000/1000000) * 100 = 1.0%
        assert abs(result["total_cash_drag"] - 1.0) < 0.01

    def test_empty_holdings(self) -> None:
        """空持仓：100%现金拖累。"""
        result = calc_position_deviation(
            holdings={},
            target_weights={"000001.SZ": 0.5, "600519.SH": 0.5},
            prices={"000001.SZ": 10.0, "600519.SH": 100.0},
            total_value=1_000_000.0,
        )

        # 平均偏差 = mean(0.5, 0.5) * 100 = 50%
        assert abs(result["mean_position_deviation"] - 50.0) < 0.01
        # 最大偏差 = 50%
        assert abs(result["max_position_deviation"] - 50.0) < 0.01
        # 现金拖累 = 100%
        assert abs(result["total_cash_drag"] - 100.0) < 0.01

    def test_zero_total_value(self) -> None:
        """总市值为0：返回全零。"""
        result = calc_position_deviation(
            holdings={},
            target_weights={"000001.SZ": 0.5},
            prices={"000001.SZ": 10.0},
            total_value=0.0,
        )

        assert result["mean_position_deviation"] == 0.0
        assert result["max_position_deviation"] == 0.0
        assert result["total_cash_drag"] == 0.0

    def test_no_target_weights(self) -> None:
        """无目标权重：返回全零。"""
        result = calc_position_deviation(
            holdings={"000001.SZ": 1000},
            target_weights={},
            prices={"000001.SZ": 10.0},
            total_value=100_000.0,
        )

        assert result["mean_position_deviation"] == 0.0

    def test_partial_fill(self) -> None:
        """部分成交：某只股票0持仓。"""
        holdings = {"000001.SZ": 10000}  # 只买到第一只
        target_weights = {"000001.SZ": 0.50, "600519.SH": 0.50}
        prices = {"000001.SZ": 10.0, "600519.SH": 100.0}
        total_value = 10000 * 10.0  # 100000, 无现金

        result = calc_position_deviation(holdings, target_weights, prices, total_value)

        # 000001: actual=100%, target=50% → dev=50%
        # 600519: actual=0%, target=50% → dev=50%
        assert abs(result["mean_position_deviation"] - 50.0) < 0.01
        assert abs(result["max_position_deviation"] - 50.0) < 0.01

    def test_cash_drag_formula(self) -> None:
        """现金拖累公式验证。"""
        # 80%仓位，20%现金
        holdings = {"000001.SZ": 8000}
        target_weights = {"000001.SZ": 1.0}
        prices = {"000001.SZ": 10.0}
        total_value = 100_000.0  # 8000*10=80000仓位 + 20000现金

        result = calc_position_deviation(holdings, target_weights, prices, total_value)

        # cash_drag = (1 - 80000/100000) * 100 = 20%
        assert abs(result["total_cash_drag"] - 20.0) < 0.01
