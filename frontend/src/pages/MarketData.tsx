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

  const { data: indices = [], isLoading: loadingIndices, isError: errorIndices } = useQuery<IndexItem[]>({
    queryKey: ["market-indices"],
    queryFn: () => apiClient.get("/market/indices").then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: sectors = [], isLoading: loadingSectors, isError: errorSectors } = useQuery<SectorItem[]>({
    queryKey: ["market-sectors"],
    queryFn: () => apiClient.get("/market/sectors").then((r) => r.data),
    staleTime: 60_000,
  });

  const { data: gainers = [], isLoading: loadingMovers, isError: errorMovers } = useQuery<MoverItem[]>({
    queryKey: ["market-top-movers-up"],
    queryFn: () => apiClient.get("/market/top-movers?direction=up&limit=5").then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: losers = [] } = useQuery<MoverItem[]>({
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
        {errorIndices && (
          <div className="px-4 py-2 rounded-lg text-center" style={{ background: `${C.down}10`, border: `1px solid ${C.down}30`, fontSize: 12, color: C.down }}>
            数据加载失败，指数行情暂不可用
          </div>
        )}
        <div className="grid grid-cols-5 gap-3">
          {loadingIndices ? (
            Array.from({ length: 5 }).map((_, i) => (
              <Card key={i} className="p-3.5">
                <div className="h-3 w-20 rounded animate-pulse mb-2" style={{ background: C.bg3 }} />
                <div className="h-6 w-24 rounded animate-pulse mb-1" style={{ background: C.bg3 }} />
                <div className="h-3 w-14 rounded animate-pulse" style={{ background: C.bg3 }} />
              </Card>
            ))
          ) : indices.length === 0 ? (
            <div className="col-span-5 text-center py-6" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
          ) : indices.map((idx) => (
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
                  {loadingMovers ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>加载中...</div>
                  ) : errorMovers ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.down }}>数据加载失败</div>
                  ) : gainers.length === 0 ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>暂无数据</div>
                  ) : gainers.map((s) => (
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
                  {loadingMovers ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>加载中...</div>
                  ) : losers.length === 0 ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>暂无数据</div>
                  ) : losers.map((s) => (
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
            ) : errorSectors ? (
              <div className="text-center py-12" style={{ color: C.down, fontSize: 12 }}>数据加载失败</div>
            ) : sectors.length === 0 ? (
              <div className="text-center py-12" style={{ color: C.text4, fontSize: 12 }}>暂无数据</div>
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
