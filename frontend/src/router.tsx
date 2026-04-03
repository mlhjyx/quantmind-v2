import { createBrowserRouter, Navigate, useRouteError } from "react-router-dom";

function RouterErrorPage() {
  const err = useRouteError() as { status?: number; statusText?: string; message?: string };
  const is404 = err?.status === 404;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100vh", fontFamily: "sans-serif", background: "#0f172a", color: "#e2e8f0" }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>{is404 ? "🗺️" : "⚠️"}</div>
      <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{is404 ? "页面不存在" : "路由错误"}</div>
      <div style={{ fontSize: 12, color: "#64748b", marginBottom: 24 }}>{err?.statusText ?? err?.message ?? "未知错误"}</div>
      <a href="/dashboard" style={{ padding: "8px 20px", borderRadius: 8, background: "#6366f1", color: "#fff", textDecoration: "none", fontSize: 14 }}>返回总览</a>
    </div>
  );
}
import { Layout } from "@/components/layout/Layout";

// Lazy page imports
import { lazy, Suspense } from "react";

function Loader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function lazyPage(importFn: () => Promise<{ default: React.ComponentType }>) {
  const Page = lazy(importFn);
  return (
    <Suspense fallback={<Loader />}>
      <Page />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    errorElement: <RouterErrorPage />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },

      // Dashboard
      { path: "dashboard", element: lazyPage(() => import("@/pages/Dashboard")) },
      { path: "dashboard/astock", element: lazyPage(() => import("@/pages/DashboardAstock")) },
      { path: "dashboard/forex", element: lazyPage(() => import("@/pages/DashboardForex")) },

      // Strategy
      { path: "strategy", element: lazyPage(() => import("@/pages/StrategyWorkspace")) },
      { path: "strategy/new", element: lazyPage(() => import("@/pages/StrategyWorkspace")) },
      { path: "strategy/:id", element: lazyPage(() => import("@/pages/StrategyWorkspace")) },

      // Backtest
      { path: "backtest/config", element: lazyPage(() => import("@/pages/BacktestConfig")) },
      { path: "backtest/history", element: lazyPage(() => import("@/pages/StrategyLibrary")) },
      { path: "backtest/:runId", element: lazyPage(() => import("@/pages/BacktestRunner")) },
      { path: "backtest/:runId/result", element: lazyPage(() => import("@/pages/BacktestResults")) },

      // Factors
      { path: "factors", element: lazyPage(() => import("@/pages/FactorLibrary")) },
      { path: "factors/compare/:id1/:id2", element: lazyPage(() => import("@/pages/FactorEvaluation")) },
      { path: "factors/:id", element: lazyPage(() => import("@/pages/FactorEvaluation")) },

      // Mining
      { path: "mining", element: lazyPage(() => import("@/pages/FactorLab")) },
      { path: "mining/tasks", element: lazyPage(() => import("@/pages/MiningTaskCenter")) },
      { path: "mining/tasks/:taskId", element: lazyPage(() => import("@/pages/MiningTaskCenter")) },

      // Pipeline / AI
      { path: "pipeline", element: lazyPage(() => import("@/pages/PipelineConsole")) },
      { path: "pipeline/agents", element: lazyPage(() => import("@/pages/AgentConfig")) },

      // PMS
      { path: "pms", element: lazyPage(() => import("@/pages/PMS")) },

      // PT Graduation
      { path: "pt-graduation", element: lazyPage(() => import("@/pages/PTGraduation")) },

      // Implemented pages
      { path: "portfolio", element: lazyPage(() => import("@/pages/Portfolio")) },
      { path: "risk", element: lazyPage(() => import("@/pages/RiskManagement")) },
      // Market / Execution / Reports
      { path: "market", element: lazyPage(() => import("@/pages/MarketData")) },
      { path: "execution", element: lazyPage(() => import("@/pages/Execution")) },
      { path: "reports", element: lazyPage(() => import("@/pages/ReportCenter")) },

      // Settings
      { path: "settings", element: lazyPage(() => import("@/pages/SystemSettings")) },
      { path: "settings/:tab", element: lazyPage(() => import("@/pages/SystemSettings")) },

      // Catch-all: redirect unknown paths to dashboard
      { path: "*", element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);
