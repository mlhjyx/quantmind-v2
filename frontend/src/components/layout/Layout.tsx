import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ToastContainer } from "@/components/ui/Toast";
import { C } from "@/theme";
import { PageErrorBoundary } from "@/components/ui/PageErrorBoundary";

function TopBar() {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  return (
    <div
      className="flex items-center gap-6 px-5 py-1.5 shrink-0"
      style={{ background: C.bg0, borderBottom: `1px solid ${C.border}` }}
    >
      {[
        { l: "沪深300", v: "3,891.62", c: "+0.87%", u: true },
        { l: "上证", v: "3,287.45", c: "+1.23%", u: true },
        { l: "创业板", v: "2,156.33", c: "+1.52%", u: true },
        { l: "成交", v: "¥1.02万亿", c: "+12%", u: true },
        { l: "北向", v: "+52.3亿", c: "", u: true },
      ].map((t, i) => (
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
            style={{ background: C.up }}
          />
          LIVE
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
