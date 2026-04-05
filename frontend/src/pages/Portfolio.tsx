import { useEffect, useState } from "react";
import axios from "axios";
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis } from "recharts";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, ChartTooltip } from "@/components/shared";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { usePortfolio } from "@/hooks/useRealtimeData";

// ── Types ──
interface Holding {
  code: string; name: string; industry: string;
  wt: number; cost: number; price: number;
  pnl: number; pnlAmt: number; days: number; signal: number;
  marketValue: number; dailyReturn: number;
}
interface SectorItem { name: string; value: number; color: string; }
interface DailyPnl   { trade_date: string; nav: number; daily_return: number; cumulative_return: number; drawdown: number; }


function SkeletonRow() {
  return (
    <tr style={{ borderTop: `1px solid ${C.border}` }}>
      {Array.from({ length: 11 }).map((_, i) => (
        <td key={i} className="py-2 px-1">
          <div className="h-3 rounded animate-pulse" style={{ background: C.bg3, width: i === 1 ? 60 : 40 }} />
        </td>
      ))}
    </tr>
  );
}

export default function Portfolio() {
  // Realtime portfolio data (5s refresh)
  const { data: rtPortfolio, isLoading: rtLoading } = usePortfolio();

  // Map realtime positions to Holding interface
  const rtHoldings: Holding[] | null = rtPortfolio
    ? rtPortfolio.positions.map((p) => ({
        code: p.code,
        name: p.name,
        industry: p.industry,
        wt: p.weight,
        cost: p.cost_price,
        price: p.last_price,
        pnl: p.pnl_pct,
        pnlAmt: p.pnl,
        days: 0, // realtime API doesn't track holding days
        signal: 0,
        marketValue: p.market_value,
        dailyReturn: p.daily_return,
      }))
    : null;

  // Historical data (sector distribution + daily PnL still from legacy API)
  const [sectorData, setSectorData] = useState<SectorItem[] | null>(null);
  const [pnlByDay, setPnlByDay]     = useState<DailyPnl[] | null>(null);
  const [loading, setLoading]       = useState(true);
  const [errors, setErrors]         = useState<string[]>([]);

  // Use realtime for holdings, fallback to legacy
  const holdings = rtHoldings;

  useEffect(() => {
    let live = true;
    const load = async () => {
      const [s, p] = await Promise.allSettled([
        axios.get<SectorItem[]>("/api/portfolio/sector-distribution", { params: { execution_mode: "live" } }),
        axios.get<DailyPnl[]>("/api/portfolio/daily-pnl", { params: { days: 20, execution_mode: "live" } }),
      ]);
      if (!live) return;

      const newErrors: string[] = [];

      if (s.status === "fulfilled") {
        setSectorData(s.value.data);
      } else {
        setSectorData([]);
        newErrors.push("行业分布数据加载失败");
      }

      if (p.status === "fulfilled") {
        setPnlByDay(p.value.data);
      } else {
        setPnlByDay([]);
        newErrors.push("每日盈亏数据加载失败");
      }

      if (newErrors.length > 0) setErrors(newErrors);
      if (live) setLoading(false);
    };
    void load();
    const id = setInterval(() => void load(), 60_000); // slower refresh for historical
    return () => { live = false; clearInterval(id); };
  }, []);

  // Show full-page skeleton on first load
  if (rtLoading && holdings === null && sectorData === null && pnlByDay === null) {
    return (
      <>
        <PageHeader title="持仓管理" titleEn="Portfolio Management" />
        <div className="flex-1 overflow-y-auto px-5 pb-5">
          <PageSkeleton cards={5} header={false} />
        </div>
      </>
    );
  }

  // Use empty arrays as safe fallbacks once loading is done
  const safeHoldings  = holdings  ?? [];
  const safeSector    = sectorData ?? [];
  const safePnlByDay  = pnlByDay  ?? [];

  // Compute summary metrics — prefer realtime, fallback to legacy
  const rtAcct = rtPortfolio?.account;
  const totalMarketValue = rtAcct?.market_value ?? safeHoldings.reduce((s, h) => s + h.marketValue, 0);
  const holdingPnl       = rtAcct?.total_pnl ?? safeHoldings.reduce((s, h) => s + h.pnlAmt, 0);
  const todayPnl         = rtAcct?.daily_pnl ?? 0;
  const totalAsset       = rtAcct?.total_asset ?? 0;
  const cash             = rtAcct?.available_cash ?? (totalAsset > 0 ? totalAsset - totalMarketValue : 0);
  const positionPct      = totalAsset > 0 ? (totalMarketValue / totalAsset * 100).toFixed(1) : "—";
  const avgDays          = safeHoldings.length
    ? Math.round(safeHoldings.reduce((s, h) => s + h.days, 0) / safeHoldings.length)
    : 0;

  const fmtCny = (v: number) => `¥${Math.abs(v).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;

  const summaryMetrics = [
    { label: "总持仓市值", value: totalMarketValue > 0 ? fmtCny(totalMarketValue) : "—",                              color: C.text1 },
    { label: "今日盈亏",   value: todayPnl !== 0 ? `${todayPnl >= 0 ? "+" : "-"}${fmtCny(todayPnl)}` : "—",          color: todayPnl >= 0 ? C.up : C.down },
    { label: "持仓盈亏",   value: `${holdingPnl >= 0 ? "+" : "-"}${fmtCny(holdingPnl)}`,                             color: holdingPnl >= 0 ? C.up : C.down },
    { label: "持仓数量",   value: `${safeHoldings.length}只`,                                                          color: C.text1 },
    { label: "平均持仓天数", value: `${avgDays}天`,                                                                   color: C.text1 },
  ];

  return (
    <>
      <PageHeader title="持仓管理" titleEn="Portfolio Management">
        <div className="flex items-center gap-4" style={{ fontSize: 11 }}>
          {rtPortfolio && !rtPortfolio.qmt_connected && (
            <span className="px-2 py-0.5 rounded" style={{ fontSize: 9, background: `${C.warn}20`, color: C.warn }}>DB数据</span>
          )}
          <span style={{ color: C.text3 }}>
            现金 <span style={{ color: C.text1, fontFamily: C.mono, fontWeight: 600 }}>{cash > 0 ? fmtCny(cash) : "—"}</span>
          </span>
          <span style={{ color: C.text3 }}>
            仓位 <span style={{ color: C.accent, fontFamily: C.mono, fontWeight: 600 }}>{positionPct !== "—" ? `${positionPct}%` : "—"}</span>
          </span>
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {/* Error banners */}
        {errors.map((msg) => (
          <ErrorBanner key={msg} message={msg} className="mb-1" />
        ))}

        {/* Summary metrics */}
        <div className="grid grid-cols-5 gap-3">
          {summaryMetrics.map((m) => (
            <Card key={m.label} className="px-3.5 py-2.5">
              <div style={{ fontSize: 9, color: C.text4 }}>{m.label}</div>
              <div style={{ fontSize: 16, fontFamily: C.mono, fontWeight: 700, color: m.color }}>{m.value}</div>
            </Card>
          ))}
        </div>

        <div className="grid grid-cols-12 gap-3">
          {/* Holdings Table */}
          <Card className="col-span-8">
            <CardHeader
              title="持仓明细"
              titleEn="Holdings Detail"
              right={
                <span style={{ fontSize: 10, color: C.text4 }}>
                  {loading ? "加载中..." : `Top ${safeHoldings.length}只`}
                </span>
              }
            />
            <div className="px-3 pb-2 overflow-auto">
              <table className="w-full" style={{ fontSize: 11 }}>
                <thead>
                  <tr style={{ color: C.text4 }}>
                    <th className="text-left py-2 font-normal">代码</th>
                    <th className="text-left py-2 font-normal">名称</th>
                    <th className="text-left py-2 font-normal">行业</th>
                    <th className="text-right py-2 font-normal">权重</th>
                    <th className="text-right py-2 font-normal">成本</th>
                    <th className="text-right py-2 font-normal">现价</th>
                    <th className="text-right py-2 font-normal">日涨跌</th>
                    <th className="text-right py-2 font-normal">盈亏%</th>
                    <th className="text-right py-2 font-normal">盈亏额</th>
                    <th className="text-right py-2 font-normal">天数</th>
                    <th className="text-right py-2 font-normal">信号</th>
                  </tr>
                </thead>
                <tbody>
                  {loading
                    ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                    : safeHoldings.length === 0
                    ? (
                        <tr>
                          <td colSpan={11}>
                            <EmptyState title="暂无持仓" description="当前组合无持仓记录" />
                          </td>
                        </tr>
                      )
                    : safeHoldings.map((h) => (
                        <tr
                          key={h.code}
                          className="cursor-pointer transition-colors"
                          style={{ borderTop: `1px solid ${C.border}` }}
                        >
                          <td className="py-2" style={{ fontFamily: C.mono, color: C.text4 }}>{h.code}</td>
                          <td className="py-2" style={{ color: C.text1 }}>{h.name}</td>
                          <td className="py-2">
                            <span className="px-1.5 py-0.5 rounded" style={{ fontSize: 9, color: C.text3, background: C.bg2 }}>
                              {h.industry}
                            </span>
                          </td>
                          <td className="text-right py-2">
                            <div className="flex items-center justify-end gap-1">
                              <div className="h-1 rounded-full" style={{ width: h.wt * 5, background: C.accent, opacity: 0.5 }} />
                              <span style={{ fontFamily: C.mono, color: C.text2 }}>{h.wt}%</span>
                            </div>
                          </td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, color: C.text3 }}>{h.cost.toFixed(2)}</td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, color: C.text1 }}>{h.price.toFixed(2)}</td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, fontWeight: 500, color: h.dailyReturn >= 0 ? C.up : C.down }}>
                            {h.dailyReturn >= 0 ? "+" : ""}{h.dailyReturn.toFixed(2)}%
                          </td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, fontWeight: 600, color: h.pnl >= 0 ? C.up : C.down }}>
                            {h.pnl >= 0 ? "+" : ""}{h.pnl.toFixed(2)}%
                          </td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, color: h.pnlAmt >= 0 ? C.up : C.down }}>
                            {h.pnlAmt >= 0 ? "+" : ""}¥{Math.abs(h.pnlAmt).toLocaleString()}
                          </td>
                          <td className="text-right py-2" style={{ fontFamily: C.mono, color: C.text3 }}>{h.days}d</td>
                          <td className="text-right py-2">
                            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: C.bg2, width: 40, marginLeft: "auto" }}>
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${h.signal * 100}%`,
                                  background: h.signal > 0.7 ? C.up : h.signal > 0.5 ? C.warn : C.down,
                                }}
                              />
                            </div>
                          </td>
                        </tr>
                      ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Right: Sector + PnL */}
          <div className="col-span-4 flex flex-col gap-3">
            <Card>
              <CardHeader title="行业分布" titleEn="Sector Allocation" />
              <div className="flex items-center px-3 pb-3">
                <div style={{ width: 140, height: 140 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={safeSector} dataKey="value" cx="50%" cy="50%" innerRadius={35} outerRadius={60} paddingAngle={2} strokeWidth={0}>
                        {safeSector.map((s, i) => <Cell key={i} fill={s.color} />)}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-1 pl-2">
                  {safeSector.length === 0
                    ? <span style={{ fontSize: 10, color: C.text4 }}>暂无数据</span>
                    : safeSector.slice(0, 6).map((s) => (
                    <div key={s.name} className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: s.color }} />
                      <span style={{ fontSize: 10, color: C.text3 }}>{s.name}</span>
                      <span className="ml-auto" style={{ fontSize: 10, fontFamily: C.mono, color: C.text2 }}>{s.value}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            <Card className="flex-1">
              <CardHeader title="每日盈亏" titleEn="Daily P&L" />
              <div className="px-3 pt-1 pb-2 flex-1" style={{ minHeight: 160 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={safePnlByDay} margin={{ top: 5, right: 5, bottom: 0, left: -10 }}>
                    <XAxis dataKey="trade_date" tick={{ fill: C.text4, fontSize: 9 }} axisLine={false} tickLine={false} interval={3} />
                    <YAxis tick={{ fill: C.text4, fontSize: 9 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v * 100).toFixed(2)}%`} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="daily_return" radius={[3, 3, 0, 0]}>
                      {safePnlByDay.map((d, i) => <Cell key={i} fill={d.daily_return >= 0 ? `${C.up}70` : `${C.down}70`} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
