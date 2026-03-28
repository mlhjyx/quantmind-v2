import { createBrowserRouter, Navigate } from "react-router-dom";
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
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },

      // Dashboard
      { path: "dashboard", element: lazyPage(() => import("@/pages/DashboardOverview")) },
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

      // PT Graduation
      { path: "pt-graduation", element: lazyPage(() => import("@/pages/PTGraduation")) },

      // Settings
      { path: "settings", element: lazyPage(() => import("@/pages/SystemSettings")) },
      { path: "settings/:tab", element: lazyPage(() => import("@/pages/SystemSettings")) },
    ],
  },
]);
