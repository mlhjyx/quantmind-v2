import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ToastContainer } from "@/components/ui/Toast";
import { C } from "@/theme";
import { PageErrorBoundary } from "@/components/ui/PageErrorBoundary";
import { useMarketOverview } from "@/hooks/useRealtimeData";

function fmtPrice(v: number): string {
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(v: number): string {
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

function fmtAmount(v: number): string {
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}万亿`;
  if (v >= 1e8) return `${(v / 1e8).toFixed(0)}亿`;
  return `${(v / 1e4).toFixed(0)}万`;
}

function TopBar() {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const { data: market } = useMarketOverview();

  const idx = market?.indices ?? {};
  const hs300 = idx["000300.SH"];
  const sh = idx["000001.SH"];
  const cy = idx["399006.SZ"];
  const isOpen = market?.is_market_open ?? false;

  // Build ticker items from live data, fallback to "—"
  const tickers = [
    { l: "沪深300", v: hs300 ? fmtPrice(hs300.price) : "—", c: hs300 ? fmtPct(hs300.change_pct) : "", u: (hs300?.change_pct ?? 0) >= 0 },
    { l: "上证", v: sh ? fmtPrice(sh.price) : "—", c: sh ? fmtPct(sh.change_pct) : "", u: (sh?.change_pct ?? 0) >= 0 },
    { l: "创业板", v: cy ? fmtPrice(cy.price) : "—", c: cy ? fmtPct(cy.change_pct) : "", u: (cy?.change_pct ?? 0) >= 0 },
    { l: "成交", v: hs300?.amount ? `¥${fmtAmount(hs300.amount)}` : "—", c: "", u: true },
  ];

  return (
    <div
      className="flex items-center gap-6 px-5 py-1.5 shrink-0"
      style={{ background: C.bg0, borderBottom: `1px solid ${C.border}` }}
    >
      {tickers.map((t, i) => (
        <div key={i} className="flex items-center gap-1.5" style={{ fontSize: 11 }}>
          <span style={{ color: C.text4 }}>{t.l}</span>
          <span style={{ color: C.text2, fontFamily: C.mono }}>{t.v}</span>
          {t.c && (
            <span style={{ color: t.u ? C.up : C.down, fontFamily: C.mono }}>{t.c}</span>
          )}
        </div>
      ))}
      <div className="ml-auto flex items-center gap-3">
        <span className="flex items-center gap-1.5" style={{ fontSize: 10, color: C.text4 }}>
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ background: isOpen ? C.up : C.text4 }}
          />
          {isOpen ? "LIVE" : "CLOSED"}
        </span>
        <span style={{ fontSize: 10, color: C.text4 }}>{dateStr}</span>
      </div>
    </div>
  );
}

export function Layout() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <NotificationProvider>
      <div
        className="h-screen w-screen overflow-hidden flex"
        style={{ background: C.bg0, fontFamily: C.font, color: C.text1 }}
      >
        {/* Sidebar */}
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

        {/* Main content */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <TopBar />
          <main className="flex-1 overflow-y-auto relative">
            {/* Subtle radial gradient background */}
            <div
              className="fixed inset-0 pointer-events-none"
              style={{
                background:
                  "radial-gradient(ellipse 80% 50% at 20% 20%, rgba(56,97,251,0.08) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 80% 80%, rgba(139,92,246,0.06) 0%, transparent 60%)",
              }}
            />
            <div className="relative z-10 p-6">
              <PageErrorBoundary>
                <Outlet />
              </PageErrorBoundary>
            </div>
          </main>
        </div>
      </div>
      <ToastContainer />
    </NotificationProvider>
  );
}
