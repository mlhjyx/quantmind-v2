import { useState } from "react";
import { Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons, ChartTooltip, Sparkline } from "@/components/shared";
import apiClient from "@/api/client";

// ---- Types ----
interface IndexItem {
  code: string;
  name: string;
  close: number;
  pre_close: number;
  pct_change: number;
  volume: number;
  amount: number;
  is_up: boolean;
  trade_date: string | null;
}

interface SectorItem {
  name: string;
  pct_change: number;
  stock_count: number;
  amount: number;
  is_up: boolean;
}

interface MoverItem {
  code: string;
  name: string;
  industry: string;
  close: number;
  pct_change: number;
}

// ---- Mock fallbacks ----
const MOCK_INDICES: IndexItem[] = [
  { code: "000300.SH", name: "沪深300", close: 3891.62, pre_close: 3858.04, pct_change: 0.87, volume: 1020000, amount: 102000000000, is_up: true, trade_date: null },
  { code: "000001.SH", name: "上证指数", close: 3287.45, pre_close: 3247.56, pct_change: 1.23, volume: 456200, amount: 45620000000, is_up: true, trade_date: null },
  { code: "399006.SZ", name: "创业板", close: 2156.33, pre_close: 2124.13, pct_change: 1.52, volume: 289100, amount: 28910000000, is_up: true, trade_date: null },
  { code: "000905.SH", name: "中证500", close: 5823.18, pre_close: 5843.03, pct_change: -0.34, volume: 123400, amount: 12340000000, is_up: false, trade_date: null },
  { code: "000016.SH", name: "上证50", close: 982.45, pre_close: 961.84, pct_change: 2.15, volume: 89200, amount: 8920000000, is_up: true, trade_date: null },
];

const MOCK_SECTORS: SectorItem[] = [
  { name: "食品饮料", pct_change: 2.35, stock_count: 82, amount: 0, is_up: true },
  { name: "电力设备", pct_change: 1.82, stock_count: 120, amount: 0, is_up: true },
  { name: "汽车", pct_change: 3.15, stock_count: 95, amount: 0, is_up: true },
  { name: "非银金融", pct_change: 0.45, stock_count: 68, amount: 0, is_up: true },
  { name: "银行", pct_change: -0.23, stock_count: 42, amount: 0, is_up: false },
  { name: "有色金属", pct_change: 1.67, stock_count: 75, amount: 0, is_up: true },
  { name: "电子", pct_change: -1.12, stock_count: 150, amount: 0, is_up: false },
  { name: "医药", pct_change: 0.89, stock_count: 180, amount: 0, is_up: true },
  { name: "计算机", pct_change: 2.56, stock_count: 130, amount: 0, is_up: true },
  { name: "机械", pct_change: 0.34, stock_count: 110, amount: 0, is_up: true },
  { name: "通信", pct_change: -0.67, stock_count: 55, amount: 0, is_up: false },
  { name: "地产", pct_change: -2.45, stock_count: 90, amount: 0, is_up: false },
  { name: "传媒", pct_change: 1.23, stock_count: 60, amount: 0, is_up: true },
  { name: "煤炭", pct_change: -0.89, stock_count: 35, amount: 0, is_up: false },
  { name: "钢铁", pct_change: 0.12, stock_count: 40, amount: 0, is_up: true },
  { name: "公用事业", pct_change: 0.56, stock_count: 70, amount: 0, is_up: true },
];

const MOCK_GAINERS: MoverItem[] = [
  { code: "002594", name: "比亚迪", industry: "汽车", close: 245.80, pct_change: 5.82 },
  { code: "603259", name: "药明康德", industry: "医药", close: 54.80, pct_change: 4.56 },
  { code: "600519", name: "贵州茅台", industry: "食品饮料", close: 1680.50, pct_change: 3.21 },
  { code: "000858", name: "五粮液", industry: "食品饮料", close: 152.30, pct_change: 2.89 },
  { code: "601899", name: "紫金矿业", industry: "有色金属", close: 15.80, pct_change: 2.45 },
];

const MOCK_LOSERS: MoverItem[] = [
  { code: "601318", name: "中国平安", industry: "非银金融", close: 48.20, pct_change: -1.85 },
  { code: "300750", name: "宁德时代", industry: "电力设备", close: 198.50, pct_change: -1.52 },
  { code: "600036", name: "招商银行", industry: "银行", close: 35.20, pct_change: -0.89 },
  { code: "002415", name: "海康威视", industry: "电子", close: 32.10, pct_change: -0.45 },
  { code: "600900", name: "长江电力", industry: "公用事业", close: 29.10, pct_change: -0.23 },
];

// Static intraday chart (no intraday API endpoint yet)
const priceData = Array.from({ length: 60 }, (_, i) => {
  const base = 3800 + i * 1.5;
  return {
    time: `${9 + Math.floor(i / 4)}:${((i % 4) * 15).toString().padStart(2, "0")}`,
    price: +(base + Math.sin(i * 0.15) * 30 + ((i * 7919) % 100) / 7).toFixed(2),
    ma5: +(base + Math.sin(i * 0.12) * 20).toFixed(2),
  };
});

function fmt(n: number) {
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number) {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function fmtAmount(a: number) {
  if (a >= 1e12) return (a / 1e12).toFixed(2) + "万亿";
  return (a / 1e8).toFixed(0) + "亿";
}

function spark(idx: IndexItem): number[] {
  const base = idx.pre_close;
  const end = idx.close;
  return Array.from({ length: 7 }, (_, i) =>
    +(base + ((end - base) * i) / 6 + Math.sin(i) * (end - base) * 0.1).toFixed(2)
  );
}

export default function MarketData() {
  const [tab, setTab] = useState("行情概览");

  const { data: indices = MOCK_INDICES, isLoading: loadingIndices } = useQuery<IndexItem[]>({
    queryKey: ["market-indices"],
    queryFn: () => apiClient.get("/market/indices").then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: sectors = MOCK_SECTORS, isLoading: loadingSectors } = useQuery<SectorItem[]>({
    queryKey: ["market-sectors"],
    queryFn: () => apiClient.get("/market/sectors").then((r) => r.data),
    staleTime: 60_000,
  });

  const { data: gainers = MOCK_GAINERS } = useQuery<MoverItem[]>({
    queryKey: ["market-top-movers-up"],
    queryFn: () => apiClient.get("/market/top-movers?direction=up&limit=5").then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: losers = MOCK_LOSERS } = useQuery<MoverItem[]>({
    queryKey: ["market-top-movers-down"],
    queryFn: () => apiClient.get("/market/top-movers?direction=down&limit=5").then((r) => r.data),
    staleTime: 30_000,
  });

  return (
    <>
      <PageHeader title="行情数据" titleEn="Market Data">
        <TabButtons tabs={["行情概览", "板块热力图", "个股详情"]} active={tab} onChange={setTab} />
        <div className="flex items-center gap-1.5" style={{ fontSize: 10, color: C.text4 }}>
          <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: C.up }} />
          {loadingIndices ? "加载中..." : "实时更新"}
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {/* Index Cards */}
        <div className="grid grid-cols-5 gap-3">
          {indices.map((idx) => (
            <Card key={idx.code} className="p-3.5">
              <div className="flex items-center justify-between mb-1">
                <span style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>{idx.name}</span>
                <span style={{ fontSize: 9, color: C.text4, fontFamily: C.mono }}>{idx.code.split(".")[0]}</span>
              </div>
              <div className="flex items-end justify-between">
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, fontFamily: C.mono, color: idx.is_up ? C.up : C.down }}>
                    {fmt(idx.close)}
                  </div>
                  <span style={{ fontSize: 11, fontFamily: C.mono, color: idx.is_up ? C.up : C.down }}>
                    {fmtPct(idx.pct_change)}
                  </span>
                </div>
                <Sparkline data={spark(idx)} color={idx.is_up ? C.up : C.down} width={56} height={24} />
              </div>
              <div style={{ fontSize: 9, color: C.text4, marginTop: 4 }}>成交 {fmtAmount(idx.amount)}</div>
            </Card>
          ))}
        </div>

        {tab === "行情概览" && (
          <div className="grid grid-cols-12 gap-3">
            <Card className="col-span-8 flex flex-col overflow-hidden">
              <CardHeader title="沪深300 分时" titleEn="Intraday" />
              <div className="px-4 pt-2 flex-1" style={{ minHeight: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={priceData} margin={{ top: 8, right: 15, bottom: 0, left: -5 }}>
                    <defs>
                      <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={C.up} stopOpacity={0.15} />
                        <stop offset="100%" stopColor={C.up} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={`${C.border}60`} strokeDasharray="3 6" vertical={false} />
                    <XAxis dataKey="time" tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} interval={9} />
                    <YAxis tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                    <Tooltip content={<ChartTooltip />} />
                    <Area name="价格" dataKey="price" stroke={C.up} strokeWidth={2} fill="url(#priceFill)" dot={false} />
                    <Area name="MA5" dataKey="ma5" stroke={C.accent} strokeWidth={1} fill="none" strokeDasharray="4 3" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <div className="col-span-4 flex flex-col gap-3">
              <Card className="flex-1 overflow-hidden">
                <CardHeader title="涨幅榜" titleEn="Top Gainers" />
                <div className="p-2 space-y-1">
                  {gainers.map((s) => (
                    <div key={s.code} className="flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer" style={{ background: `${C.up}04` }}>
                      <div>
                        <span style={{ fontSize: 11, color: C.text1 }}>{s.name}</span>
                        <span style={{ fontSize: 9, color: C.text4, marginLeft: 6, fontFamily: C.mono }}>{s.code}</span>
                      </div>
                      <span style={{ fontSize: 12, fontFamily: C.mono, fontWeight: 700, color: C.up }}>{fmtPct(s.pct_change)}</span>
                    </div>
                  ))}
                </div>
              </Card>
              <Card className="flex-1 overflow-hidden">
                <CardHeader title="跌幅榜" titleEn="Top Losers" />
                <div className="p-2 space-y-1">
                  {losers.map((s) => (
                    <div key={s.code} className="flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer" style={{ background: `${C.down}04` }}>
                      <div>
                        <span style={{ fontSize: 11, color: C.text1 }}>{s.name}</span>
                        <span style={{ fontSize: 9, color: C.text4, marginLeft: 6, fontFamily: C.mono }}>{s.code}</span>
                      </div>
                      <span style={{ fontSize: 12, fontFamily: C.mono, fontWeight: 700, color: C.down }}>{fmtPct(s.pct_change)}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        )}

        {tab === "板块热力图" && (
          <Card className="p-4">
            {loadingSectors ? (
              <div className="text-center py-12" style={{ color: C.text4, fontSize: 12 }}>加载中...</div>
            ) : (
              <div className="grid grid-cols-4 gap-2">
                {sectors.map((s) => {
                  const intensity = Math.min(Math.abs(s.pct_change) / 4, 1);
                  const bg = s.pct_change >= 0 ? C.up : C.down;
                  return (
                    <div
                      key={s.name}
                      className="rounded-xl p-4 cursor-pointer flex flex-col items-center justify-center"
                      style={{
                        background: `${bg}${Math.round(intensity * 30 + 8).toString(16).padStart(2, "0")}`,
                        border: `1px solid ${bg}20`,
                        minHeight: 100,
                      }}
                    >
                      <span style={{ fontSize: 14, color: C.text1, fontWeight: 500 }}>{s.name}</span>
                      <span style={{ fontSize: 22, fontFamily: C.mono, fontWeight: 700, color: s.pct_change >= 0 ? C.up : C.down }}>
                        {fmtPct(s.pct_change)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        )}

        {tab === "个股详情" && (
          <Card className="p-4">
            <div className="text-center py-12" style={{ color: C.text3 }}>
              <Search size={32} color={C.text4} className="mx-auto mb-3" />
              <div style={{ fontSize: 14 }}>搜索股票代码或名称查看详情</div>
              <div style={{ fontSize: 11, color: C.text4, marginTop: 4 }}>支持 A股、ETF、指数</div>
            </div>
          </Card>
        )}
      </div>
    </>
  );
}
