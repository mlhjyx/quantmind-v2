import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ToastContainer } from "@/components/ui/Toast";
import { NotificationBell } from "@/components/NotificationSystem";

export function Layout() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <NotificationProvider>
      <div className="flex h-screen w-screen overflow-hidden bg-[#080c1f]">
        {/* Sidebar */}
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

        {/* Main content area */}
        <main className="flex-1 overflow-y-auto">
          {/* Subtle radial gradient background */}
          <div
            className="fixed inset-0 pointer-events-none"
            style={{
              background:
                "radial-gradient(ellipse 80% 50% at 20% 20%, rgba(56,97,251,0.08) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 80% 80%, rgba(139,92,246,0.06) 0%, transparent 60%)",
            }}
          />
          {/* Top header bar with notification bell */}
          <div className="relative z-20 flex items-center justify-end px-6 pt-4 pb-0">
            <NotificationBell />
          </div>
          <div className="relative z-10 p-6 pt-3">
            <Outlet />
          </div>
        </main>
      </div>
      {/* Toast notifications (top-right) */}
      <ToastContainer />
    </NotificationProvider>
  );
}
