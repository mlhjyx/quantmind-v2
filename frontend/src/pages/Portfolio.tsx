import { useEffect, useState } from "react";
import axios from "axios";
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis } from "recharts";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, ChartTooltip } from "@/components/shared";

// ── Types ──
interface Holding {
  code: string; name: string; industry: string;
  wt: number; cost: number; price: number;
  pnl: number; pnlAmt: number; days: number; signal: number;
}
interface SectorItem { name: string; value: number; color: string; }
interface DailyPnl   { date: string; pnl: number; }

// ── Mock fallback data (kept as default values) ──
const MOCK_HOLDINGS: Holding[] = [
  { code: "600519", name: "贵州茅台", industry: "食品饮料", wt: 7.8, cost: 1620.5, price: 1680.5, pnl: 3.21,  pnlAmt: 12000,  days: 45, signal: 0.82 },
  { code: "300750", name: "宁德时代", industry: "电力设备", wt: 6.2, cost: 201.2,  price: 198.5,  pnl: -1.05, pnlAmt: -2700,  days: 32, signal: 0.65 },
  { code: "601318", name: "中国平安", industry: "非银金融", wt: 5.5, cost: 47.8,   price: 48.2,   pnl: 0.87,  pnlAmt: 400,    days: 28, signal: 0.71 },
  { code: "000858", name: "五粮液",   industry: "食品饮料", wt: 5.1, cost: 148.5,  price: 152.3,  pnl: 2.43,  pnlAmt: 3800,   days: 45, signal: 0.78 },
  { code: "002594", name: "比亚迪",   industry: "汽车",     wt: 4.8, cost: 235.6,  price: 245.8,  pnl: 4.12,  pnlAmt: 5100,   days: 18, signal: 0.91 },
  { code: "601899", name: "紫金矿业", industry: "有色金属", wt: 4.2, cost: 14.9,   price: 15.8,   pnl: 1.56,  pnlAmt: 1800,   days: 32, signal: 0.68 },
  { code: "600036", name: "招商银行", industry: "银行",     wt: 3.9, cost: 35.3,   price: 35.2,   pnl: -0.32, pnlAmt: -80,    days: 45, signal: 0.55 },
  { code: "002415", name: "海康威视", industry: "电子",     wt: 3.6, cost: 31.2,   price: 32.1,   pnl: 1.89,  pnlAmt: 540,    days: 12, signal: 0.73 },
  { code: "603259", name: "药明康德", industry: "医药",     wt: 3.2, cost: 52.1,   price: 54.8,   pnl: 5.18,  pnlAmt: 2700,   days: 8,  signal: 0.88 },
  { code: "600900", name: "长江电力", industry: "公用事业", wt: 2.8, cost: 28.5,   price: 29.1,   pnl: 2.11,  pnlAmt: 600,    days: 45, signal: 0.62 },
];

const MOCK_SECTOR: SectorItem[] = [
  { name: "食品饮料", value: 18.2, color: "#f59e0b" },
  { name: "电力设备", value: 12.5, color: "#818cf8" },
  { name: "非银金融", value: 10.8, color: "#8b5cf6" },
  { name: "汽车",     value: 9.3,  color: "#34d399" },
  { name: "有色金属", value: 8.1,  color: "#f87171" },
  { name: "银行",     value: 7.6,  color: "#60a5fa" },
  { name: "电子",     value: 6.4,  color: "#fb7185" },
  { name: "医药",     value: 5.8,  color: "#fbbf24" },
  { name: "公用事业", value: 4.8,  color: "#a78bfa" },
  { name: "其他",     value: 16.5, color: "#3e4158" },
];

const MOCK_DAILY_PNL: DailyPnl[] = Array.from({ length: 20 }, (_, i) => ({
  date: `3/${i + 1}`,
  pnl: +(Math.sin(i * 0.4) * 15000 + (i % 3 === 0 ? -1 : 1) * 4000).toFixed(0),
}));

function SkeletonRow() {
  return (
    <tr style={{ borderTop: `1px solid ${C.border}` }}>
      {Array.from({ length: 10 }).map((_, i) => (
        <td key={i} className="py-2 px-1">
          <div className="h-3 rounded animate-pulse" style={{ background: C.bg3, width: i === 1 ? 60 : 40 }} />
        </td>
      ))}
    </tr>
  );
}

export default function Portfolio() {
  const [holdings, setHoldings]     = useState<Holding[]>(MOCK_HOLDINGS);
  const [sectorData, setSectorData] = useState<SectorItem[]>(MOCK_SECTOR);
  const [pnlByDay, setPnlByDay]     = useState<DailyPnl[]>(MOCK_DAILY_PNL);
  const [loading, setLoading]       = useState(true);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const [h, s, p] = await Promise.allSettled([
          axios.get<Holding[]>("/api/portfolio/holdings"),
          axios.get<SectorItem[]>("/api/portfolio/sector-distribution"),
          axios.get<DailyPnl[]>("/api/portfolio/daily-pnl?days=20"),
        ]);
        if (!live) return;
        if (h.status === "fulfilled") {
          // API returns unrealized_pnl as ratio (e.g. 0.0321); map to Holding shape
          type ApiHolding = { code: string; name: string; industry: string; quantity: number; avg_cost: number; market_value: number; weight: number; unrealized_pnl: number; holding_days: number };
          const mapped: Holding[] = (h.value.data as unknown as ApiHolding[]).map((r) => ({
            code: r.code,
            name: r.name,
            industry: r.industry,
            wt: +(r.weight * 100).toFixed(2),
            cost: r.avg_cost,
            price: r.avg_cost * (1 + r.unrealized_pnl),  // derive price from cost + pnl ratio
            pnl: +(r.unrealized_pnl * 100).toFixed(2),
            pnlAmt: +(r.unrealized_pnl * r.market_value).toFixed(0),
            days: r.holding_days,
            signal: 0,
          }));
          setHoldings(mapped);
        }
        if (s.status === "fulfilled") setSectorData(s.value.data);
        if (p.status === "fulfilled") setPnlByDay(p.value.data);
      } finally {
        if (live) setLoading(false);
      }
    };
    void load();
    return () => { live = false; };
  }, []);

  // Compute summary metrics from live/mock holdings
  const holdingPnl = holdings.reduce((s, h) => s + h.pnlAmt, 0);
  const todayPnl   = pnlByDay[pnlByDay.length - 1]?.pnl ?? 0;
  const avgDays    = holdings.length
    ? Math.round(holdings.reduce((s, h) => s + h.days, 0) / holdings.length)
    : 0;

  const summaryMetrics = [
    { label: "总持仓市值", value: "¥1,285,430",                                                                       color: C.text1 },
    { label: "今日盈亏",   value: `${todayPnl >= 0 ? "+" : ""}¥${Math.abs(todayPnl).toLocaleString()}`,               color: todayPnl >= 0 ? C.up : C.down },
    { label: "持仓盈亏",   value: `${holdingPnl >= 0 ? "+" : ""}¥${Math.abs(holdingPnl).toLocaleString()}`,           color: holdingPnl >= 0 ? C.up : C.down },
    { label: "持仓数量",   value: `${holdings.length}只`,                                                             color: C.text1 },
    { label: "平均持仓天数", value: `${avgDays}天`,                                                                   color: C.text1 },
  ];

  return (
    <>
      <PageHeader title="持仓管理" titleEn="Portfolio Management">
        <div className="flex items-center gap-4" style={{ fontSize: 11 }}>
          <span style={{ color: C.text3 }}>
            现金 <span style={{ color: C.text1, fontFamily: C.mono, fontWeight: 600 }}>¥192,085</span>
          </span>
          <span style={{ color: C.text3 }}>
            仓位 <span style={{ color: C.accent, fontFamily: C.mono, fontWeight: 600 }}>85.1%</span>
          </span>
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
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
                  {loading ? "加载中..." : `Top ${holdings.length}只`}
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
                    <th className="text-right py-2 font-normal">盈亏%</th>
                    <th className="text-right py-2 font-normal">盈亏额</th>
                    <th className="text-right py-2 font-normal">天数</th>
                    <th className="text-right py-2 font-normal">信号</th>
                  </tr>
                </thead>
                <tbody>
                  {loading
                    ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                    : holdings.map((h) => (
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
                      <Pie data={sectorData} dataKey="value" cx="50%" cy="50%" innerRadius={35} outerRadius={60} paddingAngle={2} strokeWidth={0}>
                        {sectorData.map((s, i) => <Cell key={i} fill={s.color} />)}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-1 pl-2">
                  {sectorData.slice(0, 6).map((s) => (
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
                  <BarChart data={pnlByDay} margin={{ top: 5, right: 5, bottom: 0, left: -10 }}>
                    <XAxis dataKey="date" tick={{ fill: C.text4, fontSize: 9 }} axisLine={false} tickLine={false} interval={3} />
                    <YAxis tick={{ fill: C.text4, fontSize: 9 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                      {pnlByDay.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? `${C.up}70` : `${C.down}70`} />)}
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
