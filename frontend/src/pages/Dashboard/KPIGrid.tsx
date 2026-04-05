import { Card, Sparkline } from "@/components/shared";
import { C } from "@/theme";
import type { DashboardSummary } from "@/types/dashboard";

export interface KPICard {
  label: string; en: string; value: string; sub?: string;
  valueC?: string; subC?: string; spark?: number[]; sparkC?: string; accent?: boolean;
}

export function KPIGrid({ summary, rtAccount }: { summary: DashboardSummary | null; rtAccount?: { total_asset: number; daily_pnl: number; total_pnl: number; total_pnl_pct: number; available_cash: number; market_value: number } }) {
  // Prefer realtime data for NAV and daily P&L
  const nav    = rtAccount?.total_asset ?? summary?.nav ?? 0;
  const cumRet = rtAccount ? (rtAccount.total_pnl_pct / 100) : (summary?.cumulative_return ?? 0);
  const dayPnl = rtAccount?.daily_pnl ?? (summary ? (summary.daily_return ?? 0) * (summary.nav ?? 0) : 0);
  const dayRet = rtAccount && nav > 0 ? dayPnl / nav : (summary?.daily_return ?? 0);
  const sharpe = summary?.sharpe ?? 0;
  const mdd    = summary?.mdd ?? 0;

  const cards: KPICard[] = [
    {
      label: "总权益", en: "EQUITY",
      value: nav > 0 ? `¥${nav.toLocaleString("zh", { maximumFractionDigits: 0 })}` : "—",
      sub: cumRet !== 0 ? `${cumRet >= 0 ? "+" : ""}${(cumRet * 100).toFixed(2)}%` : (rtAccount ? `持仓 ${rtAccount.market_value.toLocaleString("zh", { maximumFractionDigits: 0 })}` : "—"),
      subC: cumRet >= 0 ? C.up : C.down,
      sparkC: C.up, accent: true,
    },
    {
      label: "今日P&L", en: "TODAY",
      value: dayPnl !== 0 ? `${dayPnl >= 0 ? "+" : "-"}¥${Math.abs(dayPnl).toLocaleString("zh", { maximumFractionDigits: 0 })}` : "—",
      valueC: dayPnl >= 0 ? C.up : C.down,
      sub: dayRet !== 0 ? `${dayRet >= 0 ? "+" : ""}${(dayRet * 100).toFixed(2)}%` : "—",
      subC: dayRet >= 0 ? C.up : C.down,
      sparkC: dayRet >= 0 ? C.up : C.down,
    },
    {
      label: "年化收益", en: "CAGR",
      value: "—", valueC: C.up,
      sub: "—", subC: C.up,
    },
    {
      label: "Sharpe", en: "DSR✓",
      value: sharpe !== 0 ? sharpe.toFixed(2) : "—",
      sub: sharpe === 0 ? "数据积累中" : "—", subC: C.text3,
    },
    {
      label: "最大回撤", en: "MDD",
      value: mdd !== 0 ? `${(mdd * 100).toFixed(2)}%` : "—", valueC: C.down,
      sub: mdd === 0 ? "数据积累中" : "—", subC: C.down,
    },
    {
      label: "胜率", en: "Win%",
      value: "—",
      sub: "—", subC: C.text3,
    },
    {
      label: "仓位", en: "POS",
      value: rtAccount ? `${(rtAccount.market_value / (rtAccount.total_asset || 1) * 100).toFixed(1)}%` : (summary ? `${(100 - (summary.cash_ratio ?? 0) * 100).toFixed(1)}%` : "—"),
      sub: summary ? `${summary.position_count ?? 0}只持仓` : "—", subC: C.text3,
    },
    {
      label: "风险", en: "RISK",
      value: "LOW", valueC: C.up,
      sub: "—", subC: C.warn,
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {cards.map((m, i) => (
        <Card key={i} className="p-3.5 flex flex-col justify-between overflow-hidden" style={{
          minHeight: 92,
          ...(m.accent ? { borderColor: `${C.accent}25`, background: `linear-gradient(135deg, ${C.bg1}, ${C.accent}06)` } : {}),
        }}>
          <div className="flex items-center justify-between">
            <span style={{ fontSize: 11, color: C.text3 }}>{m.label}</span>
            <span style={{ fontSize: 9, color: C.text4 }}>{m.en}</span>
          </div>
          <div className="flex items-end justify-between mt-auto gap-1">
            <div className="min-w-0">
              <div style={{
                fontSize: 20, fontWeight: 700, color: m.valueC ?? C.text1, fontFamily: C.mono, lineHeight: 1.1,
                ...(m.valueC ? { textShadow: `0 0 16px ${m.valueC}30` } : {}),
              }}>{m.value}</div>
              {m.sub && (
                <span className="block truncate" style={{ fontSize: 10, color: m.subC ?? C.text3, marginTop: 2 }}>
                  {m.sub}
                </span>
              )}
            </div>
            {m.spark && <Sparkline data={m.spark} color={m.sparkC ?? C.accent} width={48} height={22} />}
          </div>
        </Card>
      ))}
    </div>
  );
}
