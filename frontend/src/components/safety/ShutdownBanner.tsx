/**
 * ShutdownBanner — Dashboard 顶部维护模式提醒.
 *
 * Frontend Design v3 §2.5 — Only render when system is in "maintenance" state:
 *   - 0 持仓 (positions count === 0)
 *   - cash 接近 ¥993,520 (post-2026-04-29 清仓)
 *   - env: LIVE_TRADING_DISABLED=true
 *
 * 业务目的: 用户看到 Dashboard 0 持仓 + ¥993,520 时, 立即明白 "为什么".
 * 不显示 ADR/LL 元数据 — 仅业务事实 + reason + cash + 上次清仓日期.
 */

import { Wrench, ChevronRight } from "lucide-react";
import { C } from "@/theme";

interface ShutdownBannerProps {
  positionsCount: number;
  cashAmount: number; // ¥
  liveTradingDisabled: boolean;
}

const SHUTDOWN_THRESHOLD_CASH = 950_000; // 阈值: cash > 95 万 + 0 持仓 → maintenance
const SHUTDOWN_DATE = "2026-04-29";

export function ShutdownBanner({ positionsCount, cashAmount, liveTradingDisabled }: ShutdownBannerProps) {
  const isMaintenance =
    positionsCount === 0 && cashAmount >= SHUTDOWN_THRESHOLD_CASH && liveTradingDisabled;

  if (!isMaintenance) return null;

  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 rounded-lg"
      style={{
        background: `${C.text4}15`,
        border: `1px dashed ${C.text3}50`,
      }}
    >
      <Wrench size={15} color={C.text3} />
      <div className="flex-1">
        <div style={{ fontSize: 12, color: C.text2, fontWeight: 500 }}>
          维护模式 · 0 持仓
        </div>
        <div className="flex items-center gap-3 mt-0.5" style={{ fontSize: 11, color: C.text3 }}>
          <span>
            上次清仓:{" "}
            <span style={{ fontFamily: C.mono, color: C.text2 }}>{SHUTDOWN_DATE}</span>
          </span>
          <span>·</span>
          <span>
            现金:{" "}
            <span style={{ fontFamily: C.mono, color: C.text1, fontWeight: 600 }}>
              ¥{cashAmount.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}
            </span>
          </span>
          <span>·</span>
          <span>实盘交易已锁 (LIVE_TRADING_DISABLED=true)</span>
        </div>
      </div>
      <button
        className="flex items-center gap-1 px-2.5 py-1 rounded cursor-pointer"
        style={{
          background: C.bg2,
          border: `1px solid ${C.border}`,
          fontSize: 11,
          color: C.text3,
        }}
        onClick={() => window.open("/system/settings", "_blank")}
        title="跳转到系统设置查看 .env 状态"
      >
        查看 ENV
        <ChevronRight size={11} />
      </button>
    </div>
  );
}
