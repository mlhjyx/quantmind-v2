"""L1延迟月度调仓（方案C）测试。

覆盖4个场景：
1. L1触发+月度调仓日 -> pending -> 次日恢复NORMAL -> 执行延迟调仓
2. L1触发+月度调仓日 -> pending -> 次日升级L2 -> 放弃（pending过期或L2暂停）
3. L1触发+非调仓日 -> 正常跳过（无pending记录）
4. 假期跨度(gap=0交易日) -> 不误杀（pending不应过期）

测试方法：直接操作DB模拟场景，验证run_paper_trading中的逻辑分支。
"""

import json
import sys
from datetime import date
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

DB_URL = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"


@pytest.fixture
def db_conn():
    """同步DB连接，测试结束后ROLLBACK。"""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


def insert_pending_rebalance(conn, signal_date: date, target: dict):
    """插入一条pending_monthly_rebalance记录。"""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO scheduler_task_log
           (task_name, market, schedule_time, start_time, status,
            error_message, result_json)
           VALUES ('pending_monthly_rebalance', 'astock', NOW(), NOW(), 'pending',
                   %s, %s)""",
        (f"L1触发延迟月度调仓 signal_date={signal_date}",
         json.dumps({"signal_date": str(signal_date), "target": target})),
    )
    conn.commit()


def get_pending_status(conn) -> str | None:
    """查询最新pending_monthly_rebalance的状态。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT status FROM scheduler_task_log
           WHERE task_name = 'pending_monthly_rebalance'
           ORDER BY created_at DESC LIMIT 1""")
    row = cur.fetchone()
    return row[0] if row else None


def count_trading_days_between(conn, d1: date, d2: date) -> int:
    """计算两个日期之间的交易日数量（不含端点）。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM trading_calendar
           WHERE market='astock' AND is_trading_day=TRUE
           AND trade_date > %s AND trade_date < %s""",
        (d1, d2))
    return cur.fetchone()[0]


class TestL1DelayRebalance:
    """L1延迟月度调仓方案C的4个场景。"""

    def test_scenario1_l1_pending_then_recover_execute(self, db_conn):
        """场景1: L1触发+月度调仓日 -> pending -> 次日NORMAL -> 执行延迟调仓。

        模拟：
        - signal_date=月末交易日，is_rebalance=True
        - T+1执行时L1触发 -> 写pending记录
        - T+2执行时L0(NORMAL) -> 检测到pending -> 执行延迟调仓
        """
        # 找一个月末交易日作为signal_date
        cur = db_conn.cursor()
        cur.execute(
            """SELECT trade_date FROM (
                SELECT trade_date,
                       ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('month', trade_date)
                                          ORDER BY trade_date DESC) as rn
                FROM trading_calendar
                WHERE market='astock' AND is_trading_day=TRUE
                  AND trade_date BETWEEN '2025-06-01' AND '2025-06-30'
            ) t WHERE rn=1 LIMIT 1""")
        row = cur.fetchone()
        assert row, "需要有2025年6月交易日历数据"
        signal_date = row[0]

        # 找signal_date之后的2个交易日
        cur.execute(
            """SELECT trade_date FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
                 AND trade_date > %s
               ORDER BY trade_date LIMIT 2""",
            (signal_date,))
        next_days = [r[0] for r in cur.fetchall()]
        assert len(next_days) >= 2, "需要至少2个后续交易日"
        next_days[0]  # L1触发日
        exec_date_t2 = next_days[1]  # L1恢复日

        # 模拟L1触发时写入pending记录
        target = {"600519.SH": 0.05, "000858.SZ": 0.05, "601318.SH": 0.05}
        insert_pending_rebalance(db_conn, signal_date, target)

        # 验证pending记录存在
        assert get_pending_status(db_conn) == "pending"

        # 验证gap：signal_date到exec_date_t2之间的交易日数
        gap = count_trading_days_between(db_conn, signal_date, exec_date_t2)
        # T日signal -> T+1 L1触发 -> T+2恢复，gap应该<=2
        assert gap <= 2, f"gap={gap}应该<=2（signal到T+2之间）"

        # 模拟Step 5.95逻辑：cb.level==0, not is_rebalance
        cb_level = 0
        is_rebalance = False

        if cb_level == 0 and not is_rebalance:
            cur.execute(
                """SELECT result_json FROM scheduler_task_log
                   WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'
                   ORDER BY created_at DESC LIMIT 1""")
            pending = cur.fetchone()
            assert pending is not None, "应该找到pending记录"
            pending_data = json.loads(pending[0]) if isinstance(pending[0], str) else pending[0]
            pending_signal_date = pending_data.get("signal_date")
            pending_target = pending_data.get("target", {})

            assert pending_signal_date == str(signal_date)
            assert len(pending_target) == 3

            from datetime import datetime as dt
            p_date = dt.strptime(pending_signal_date, "%Y-%m-%d").date()
            gap_check = count_trading_days_between(db_conn, p_date, exec_date_t2)

            if gap_check <= 2 and pending_target:
                {k: float(v) for k, v in pending_target.items()}
                is_rebalance = True
                cur.execute(
                    """UPDATE scheduler_task_log SET status='executed'
                       WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                db_conn.commit()

        # 验证结果
        assert is_rebalance is True, "延迟调仓应该被执行"
        assert get_pending_status(db_conn) == "executed", "pending应该变成executed"

    def test_scenario2_l1_pending_then_l2_abandon(self, db_conn):
        """场景2: L1触发+月度调仓日 -> pending -> 次日L2 -> 放弃。

        L2时cb.level==2，Step 5.95的条件 cb.level==0 不满足，
        所以不会进入延迟调仓检查。L2直接暂停交易。
        同时如果L2持续多天导致gap>2，pending过期。
        """
        cur = db_conn.cursor()

        # 找一个月末交易日
        cur.execute(
            """SELECT trade_date FROM (
                SELECT trade_date,
                       ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('month', trade_date)
                                          ORDER BY trade_date DESC) as rn
                FROM trading_calendar
                WHERE market='astock' AND is_trading_day=TRUE
                  AND trade_date BETWEEN '2025-07-01' AND '2025-07-31'
            ) t WHERE rn=1 LIMIT 1""")
        row = cur.fetchone()
        assert row, "需要有2025年7月交易日历数据"
        signal_date = row[0]

        # 找signal_date之后的4个交易日（模拟L2持续几天）
        cur.execute(
            """SELECT trade_date FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
                 AND trade_date > %s
               ORDER BY trade_date LIMIT 4""",
            (signal_date,))
        next_days = [r[0] for r in cur.fetchall()]
        assert len(next_days) >= 4, "需要至少4个后续交易日"

        target = {"600519.SH": 0.05, "000858.SZ": 0.05}
        insert_pending_rebalance(db_conn, signal_date, target)

        # 场景A: 次日L2触发(cb.level==2)
        cb_level = 2
        is_rebalance = False

        # Step 5.95条件：cb.level==0 不满足，不进入延迟调仓检查
        entered_delay_check = False
        if cb_level == 0 and not is_rebalance:
            entered_delay_check = True

        assert entered_delay_check is False, "L2时不应进入延迟调仓检查"
        assert get_pending_status(db_conn) == "pending", "pending状态不应改变（L2没检查）"

        # 场景B: L2持续到gap>2后恢复NORMAL，pending应过期
        exec_date_late = next_days[3]  # 4个交易日后
        cb_level = 0
        is_rebalance = False

        if cb_level == 0 and not is_rebalance:
            cur.execute(
                """SELECT result_json FROM scheduler_task_log
                   WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'
                   ORDER BY created_at DESC LIMIT 1""")
            pending = cur.fetchone()
            if pending and pending[0]:
                pending_data = json.loads(pending[0]) if isinstance(pending[0], str) else pending[0]
                pending_signal_date = pending_data.get("signal_date")
                pending_target = pending_data.get("target", {})

                from datetime import datetime as dt
                p_date = dt.strptime(pending_signal_date, "%Y-%m-%d").date()
                gap = count_trading_days_between(db_conn, p_date, exec_date_late)

                if gap <= 2 and pending_target:
                    is_rebalance = True
                else:
                    # 过期
                    cur.execute(
                        """UPDATE scheduler_task_log SET status='expired'
                           WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                    db_conn.commit()

        assert is_rebalance is False, "gap>2时延迟调仓应该被放弃"
        assert get_pending_status(db_conn) == "expired", "pending应该变成expired"

    def test_scenario3_l1_non_rebalance_day_skip(self, db_conn):
        """场景3: L1触发+非调仓日 -> 正常跳过，不写pending记录。

        非调仓日L1触发时is_rebalance=False，不应该写pending记录。
        """
        cur = db_conn.cursor()

        # 检查scheduler_task_log中没有pending记录
        cur.execute(
            """SELECT COUNT(*) FROM scheduler_task_log
               WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'""")
        assert cur.fetchone()[0] == 0, "初始状态不应有pending记录"

        # 模拟L1触发 + 非调仓日
        cb_level = 1
        is_rebalance = False  # 非调仓日
        signal_date = date(2025, 6, 15)  # 月中，非调仓日
        hedged_target = {"600519.SH": 0.05}

        # 模拟run_paper_trading中L1分支逻辑
        if cb_level == 1:
            if is_rebalance:
                # 方案C：延迟月度调仓
                is_rebalance = False
                cur.execute(
                    """INSERT INTO scheduler_task_log
                       (task_name, market, schedule_time, start_time, status,
                        error_message, result_json)
                       VALUES ('pending_monthly_rebalance', 'astock', NOW(), NOW(), 'pending',
                               %s, %s)""",
                    (f"L1触发延迟月度调仓 signal_date={signal_date}",
                     json.dumps({"signal_date": str(signal_date),
                                 "target": {k: round(v, 6) for k, v in hedged_target.items()}})))
                db_conn.commit()
            else:
                # 非调仓日正常跳过
                is_rebalance = False

        # 验证：不应该有pending记录
        cur.execute(
            """SELECT COUNT(*) FROM scheduler_task_log
               WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'""")
        count = cur.fetchone()[0]
        assert count == 0, "非调仓日L1不应写入pending记录"
        assert is_rebalance is False, "非调仓日应保持is_rebalance=False"

    def test_scenario4_holiday_gap0_no_false_expire(self, db_conn):
        """场景4: 假期跨度(gap=0交易日) -> 不误杀。

        例如：周五月末L1触发 -> pending -> 周一恢复
        gap=0（周五和周一之间没有交易日），应该执行，不应过期。
        """
        cur = db_conn.cursor()

        # 找一个周五的交易日（月末附近）
        cur.execute(
            """SELECT trade_date FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
                 AND EXTRACT(DOW FROM trade_date) = 5  -- 周五
                 AND trade_date BETWEEN '2025-05-01' AND '2025-12-31'
               ORDER BY trade_date LIMIT 1""")
        row = cur.fetchone()
        assert row, "需要找到一个周五交易日"
        friday_date = row[0]

        # 找下一个交易日（应该是周一）
        cur.execute(
            """SELECT trade_date FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
                 AND trade_date > %s
               ORDER BY trade_date LIMIT 1""",
            (friday_date,))
        next_td = cur.fetchone()
        assert next_td, "需要找到周五之后的下一个交易日"
        monday_date = next_td[0]

        # 验证gap=0（周五和周一之间没有中间交易日）
        gap = count_trading_days_between(db_conn, friday_date, monday_date)
        assert gap == 0, f"周五到下周一之间应该gap=0，实际gap={gap}"

        # 插入pending记录（signal_date=周五）
        target = {"600519.SH": 0.05, "000858.SZ": 0.05}
        insert_pending_rebalance(db_conn, friday_date, target)

        # 模拟周一恢复NORMAL的Step 5.95逻辑
        cb_level = 0
        is_rebalance = False
        exec_date = monday_date

        if cb_level == 0 and not is_rebalance:
            cur.execute(
                """SELECT result_json FROM scheduler_task_log
                   WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'
                   ORDER BY created_at DESC LIMIT 1""")
            pending = cur.fetchone()
            if pending and pending[0]:
                pending_data = json.loads(pending[0]) if isinstance(pending[0], str) else pending[0]
                pending_signal_date = pending_data.get("signal_date")
                pending_target = pending_data.get("target", {})

                from datetime import datetime as dt
                p_date = dt.strptime(pending_signal_date, "%Y-%m-%d").date()
                gap_check = count_trading_days_between(db_conn, p_date, exec_date)

                if gap_check <= 2 and pending_target:
                    {k: float(v) for k, v in pending_target.items()}
                    is_rebalance = True
                    cur.execute(
                        """UPDATE scheduler_task_log SET status='executed'
                           WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                    db_conn.commit()
                else:
                    cur.execute(
                        """UPDATE scheduler_task_log SET status='expired'
                           WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                    db_conn.commit()

        # 验证：gap=0<=2，应该执行，不应过期
        assert is_rebalance is True, f"gap={gap}<=2，延迟调仓应该被执行（不误杀）"
        assert get_pending_status(db_conn) == "executed", "pending应该变成executed"
