/**
 * AttributionPanel — Dashboard 归因分析 widget.
 *
 * iter 147 W2-F F6 closure — daily_attribution table (iter 146 migration applied)
 * + /api/attribution/{latest,history} endpoints (iter 147 backend layer added).
 *
 * Surfaces latest DailyAttribution row to operator. Sibling AlertsPanel pattern.
 * Read-only display: nav_change / alpha_vs_benchmark / unexplained_residual
 * top-3 by_factor + by_sector contributors.
 *
 * fail-loud render guard (LL-205): loading skeleton → error card with retry
 * → no-data state → populated state. No silent fallback.
 */

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";
import { TrendingUp, TrendingDown, AlertTriangle, RefreshCw, BarChart3 } from "lucide-react";
import { getLatestAttribution, type AttributionRow } from "@/api/attribution";

function formatBps(bps: number): string {
  return `${bps >= 0 ? "+" : ""}${bps.toFixed(1)} bps`;
}

function formatPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(3)}%`;
}

function topNContributors(
  data: Record<string, number>,
  n: number,
): Array<{ key: string; value: number }> {
  return Object.entries(data)
    .map(([key, value]) => ({ key, value }))
    .filter((e) => Math.abs(e.value) > 1e-6) // exclude zeros
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, n);
}

function ContributorRow({ label, bps }: { label: string; bps: number }) {
  const color = bps >= 0 ? C.up : C.down; // A股惯例 涨红跌绿
  return (
    <div className="flex items-center justify-between" style={{ fontSize: 11 }}>
      <span style={{ color: C.text3 }}>{label}</span>
      <span style={{ color, fontFamily: C.mono, fontWeight: 500 }}>
        {bps >= 0 ? "+" : ""}{bps.toFixed(1)} bps
      </span>
    </div>
  );
}

export function AttributionPanel() {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["attribution-latest", "paper"],
    queryFn: () => getLatestAttribution("paper"),
    refetchInterval: 60_000, // 1min polling (daily Beat fires 16:30, no real-time needed)
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <Card className="flex flex-col" style={{ maxHeight: 280 }}>
        <CardHeader title="归因分析" titleEn="Attribution" />
        <div className="p-3 space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 rounded-lg animate-pulse" style={{ background: C.bg2 }} />
          ))}
        </div>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="flex flex-col" style={{ maxHeight: 280, border: `1px solid ${C.up}40` }}>
        <CardHeader title="归因分析" titleEn="Attribution" />
        <div className="p-3 text-center" style={{ fontSize: 11, color: C.up }}>
          <AlertTriangle size={20} color={C.up} className="mx-auto mb-2" />
          <div style={{ fontWeight: 600 }}>归因数据加载失败</div>
          <div style={{ color: C.text3, marginTop: 4, marginBottom: 8 }}>
            {error instanceof Error ? error.message : "未知错误"}
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1 rounded inline-flex items-center gap-1 cursor-pointer"
            style={{ fontSize: 11, background: C.accent, color: "#fff" }}
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
            重试
          </button>
        </div>
      </Card>
    );
  }

  // data === null when no rows yet (daily-attribution-compute hasn't fired or Servy
  // restart blocker prevents writes; surfaced explicitly per §v9.48 honest progress)
  if (!data) {
    return (
      <Card className="flex flex-col" style={{ maxHeight: 280 }}>
        <CardHeader title="归因分析" titleEn="Attribution" />
        <div className="p-4 text-center" style={{ fontSize: 11, color: C.text4 }}>
          <BarChart3 size={20} color={C.text4} className="mx-auto mb-2" />
          <div>暂无归因数据</div>
          <div style={{ marginTop: 4 }}>daily-attribution-compute Beat 16:30 Mon-Fri 触发</div>
        </div>
      </Card>
    );
  }

  const navChangeBps = data.nav_change_bps;
  const alphaBps = data.alpha_vs_benchmark_bps;
  const residualBps = data.unexplained_residual_bps;
  const navUp = navChangeBps >= 0;
  const NavIcon = navUp ? TrendingUp : TrendingDown;
  const navColor = navUp ? C.up : C.down; // 涨红跌绿

  const topFactors = topNContributors(data.by_factor, 3);
  const topSectors = topNContributors(data.by_sector, 3);
  const residualHigh = Math.abs(residualBps) > 20.0; // matches fire_residual_alert threshold

  return (
    <Card className="flex flex-col" style={{ maxHeight: 320 }}>
      <CardHeader
        title="归因分析"
        titleEn="Attribution"
        right={
          <span style={{ fontSize: 10, color: C.text4, fontFamily: C.mono }}>
            {data.trade_date ?? "—"}
          </span>
        }
      />
      <div className="p-3 space-y-3">
        {/* Top metrics row */}
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-lg p-2" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 9, color: C.text4 }}>NAV 变化</div>
            <div className="flex items-center gap-1 mt-1">
              <NavIcon size={11} color={navColor} />
              <span style={{ fontSize: 12, color: navColor, fontFamily: C.mono, fontWeight: 600 }}>
                {formatBps(navChangeBps)}
              </span>
            </div>
            <div style={{ fontSize: 9, color: C.text4, fontFamily: C.mono, marginTop: 2 }}>
              {formatPct(data.nav_change_pct)}
            </div>
          </div>
          <div className="rounded-lg p-2" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 9, color: C.text4 }}>α vs 基准</div>
            <div style={{ fontSize: 12, color: alphaBps >= 0 ? C.up : C.down, fontFamily: C.mono, fontWeight: 600, marginTop: 4 }}>
              {formatBps(alphaBps)}
            </div>
          </div>
          <div
            className="rounded-lg p-2"
            style={{
              background: residualHigh ? `${C.warn}15` : C.bg2,
              border: `1px solid ${residualHigh ? C.warn : C.border}`,
            }}
            title={residualHigh ? "残差 > 20 bps 阈值, 可能存在未归因 alpha 或 cost gap" : ""}
          >
            <div style={{ fontSize: 9, color: residualHigh ? C.warn : C.text4 }}>
              残差 {residualHigh && "⚠"}
            </div>
            <div style={{ fontSize: 12, color: residualHigh ? C.warn : C.text2, fontFamily: C.mono, fontWeight: 600, marginTop: 4 }}>
              {formatBps(residualBps)}
            </div>
          </div>
        </div>

        {/* Top factor contributors */}
        {topFactors.length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>因子贡献 (Top 3)</div>
            <div className="space-y-1">
              {topFactors.map((f) => (
                <ContributorRow key={f.key} label={f.key} bps={f.value * 10000.0} />
              ))}
            </div>
          </div>
        )}

        {/* Top sector contributors */}
        {topSectors.length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>行业贡献 (Top 3)</div>
            <div className="space-y-1">
              {topSectors.map((s) => (
                <ContributorRow key={s.key} label={s.key} bps={s.value * 10000.0} />
              ))}
            </div>
          </div>
        )}

        {/* No contributors at all = latest row has no attributable inputs */}
        {topFactors.length === 0 && topSectors.length === 0 && (
          <div className="text-center py-2" style={{ fontSize: 10, color: C.text4 }}>
            当前归因行无持仓/成交/行业输入贡献
          </div>
        )}
      </div>
    </Card>
  );
}

// Helper export for testing
export { topNContributors };
// Helper alias to silence "unused" warning on AttributionRow re-export.
export type { AttributionRow };
