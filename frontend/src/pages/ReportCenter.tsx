import { useEffect, useRef, useState } from "react";
import { FileText, Download, TrendingUp, BarChart3, Shield, Brain, AlertCircle, CheckCircle2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons } from "@/components/shared";
import apiClient from "@/api/client";
import {
  generateReport,
  listStrategyReports,
  type GenerateReportResponse,
  type ReportListingRow,
} from "@/api/reports";

// Iter 35 wire of iter 30/31/32 backend lifecycle: generateReport → task_id
// capture + toast feedback; listStrategyReports → 策略报告 tab artifact rows.
// DEFAULT_STRATEGY_ID is a placeholder; future iter can promote to user input
// or settings.PAPER_STRATEGY_ID-equivalent context fetch.
const DEFAULT_STRATEGY_ID = "default-strategy";
const GENERATE_REFRESH_DELAY_MS = 3000;

// ---- Types ----
interface ReportItem {
  run_id: string;
  name: string;
  status: string;
  annual_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  total_trades: number | null;
  start_date: string | null;
  end_date: string | null;
  created_at: string | null;
}

interface PeriodStats {
  return: number;
  trade_days: number;
  avg_turnover: number;
}

interface QuickStats {
  today: PeriodStats;
  week: PeriodStats;
  month: PeriodStats;
  year: PeriodStats;
  latest_position_count: number;
  as_of: string;
}


const templates = [
  { name: "策略绩效报告", icon: TrendingUp, desc: "净值曲线、收益归因、风险指标", color: C.up },
  { name: "因子分析报告", icon: BarChart3, desc: "因子IC/IR、衰减检测、相关性", color: C.accent },
  { name: "风险控制报告", icon: Shield, desc: "VaR、压力测试、限额使用", color: C.warn },
  { name: "AI闭环报告", icon: Brain, desc: "挖掘进度、候选因子、自动化效率", color: "#a5b4fc" },
];

function fmtPct(n: number | null) {
  if (n == null) return "—";
  return (n >= 0 ? "+" : "") + (n * 100).toFixed(2) + "%";
}

function fmtDate(s: string | null) {
  return s ? s.slice(0, 10) : "—";
}

const PERIOD_LABELS: Record<keyof Omit<QuickStats, "latest_position_count" | "as_of">, string> = {
  today: "今日",
  week: "本周",
  month: "本月",
  year: "今年",
};

export default function ReportCenter() {
  const [tab, setTab] = useState("报告列表");
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const queryClient = useQueryClient();
  // Reviewer P2-2 fix: track refresh timer for cleanup on unmount (反 setTimeout leak).
  const refreshTimerRef = useRef<number | null>(null);

  const { data: reports = [], isLoading: loadingReports, isError: errorReports } = useQuery<ReportItem[]>({
    queryKey: ["reports-list"],
    queryFn: () => apiClient.get("/reports/list").then((r) => r.data),
    staleTime: 60_000,
  });

  const { data: quickStats, isLoading: loadingStats, isError: errorStats } = useQuery<QuickStats>({
    queryKey: ["reports-quick-stats"],
    queryFn: () => apiClient.get("/reports/quick-stats").then((r) => r.data),
    staleTime: 60_000,
  });

  // Iter 35: strategy report artifacts (iter 32 endpoint /api/reports/{sid}/list).
  const {
    data: strategyReports = [],
    isLoading: loadingStrategyReports,
    isError: errorStrategyReports,
  } = useQuery<ReportListingRow[]>({
    queryKey: ["strategy-reports", DEFAULT_STRATEGY_ID],
    queryFn: () => listStrategyReports(DEFAULT_STRATEGY_ID),
    staleTime: 60_000,
  });

  // Iter 35: useMutation for /generate (iter 30 endpoint) — captures real Celery
  // task_id + provides UI feedback (reverts the iter 30 pre-fix fire-and-forget).
  const generateMutation = useMutation<GenerateReportResponse, Error>({
    mutationFn: () => generateReport(),
    onSuccess: (data) => {
      setFeedback({
        kind: "success",
        text: `生成任务已派发 task_id=${data.task_id.slice(0, 8)}... (${GENERATE_REFRESH_DELAY_MS / 1000}s 后自动刷新)`,
      });
      // Auto-refresh strategy reports after Celery worker likely finishes.
      // Reviewer P2-2 fix: store timer ID + clear on unmount (see useEffect below).
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
      refreshTimerRef.current = window.setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["strategy-reports"] });
        refreshTimerRef.current = null;
      }, GENERATE_REFRESH_DELAY_MS);
    },
    onError: (err) => {
      setFeedback({ kind: "error", text: `生成失败: ${err.message}` });
    },
  });

  // Auto-clear feedback after 8s (反 stale toast persistence).
  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(() => setFeedback(null), 8000);
    return () => clearTimeout(t);
  }, [feedback]);

  // Reviewer P2-2 fix: cleanup pending refresh timer on unmount (反 setTimeout
  // leak invalidating queries after the page is gone).
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, []);

  const periods = (["today", "week", "month", "year"] as const).map((k) => ({
    key: k,
    label: PERIOD_LABELS[k],
    stats: quickStats?.[k],
  }));

  return (
    <>
      <PageHeader title="报告中心" titleEn="Report Center">
        <TabButtons tabs={["报告列表", "策略报告", "快速统计", "模板"]} active={tab} onChange={setTab} />
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer disabled:opacity-50"
          style={{ background: C.accentSoft, color: "#a5b4fc", fontSize: 11, border: `1px solid ${C.accent}30` }}
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
        >
          <FileText size={13} /> {generateMutation.isPending ? "生成中..." : "生成报告"}
        </button>
      </PageHeader>

      {feedback && (
        <div
          className="mx-5 mt-2 px-3 py-2 rounded-lg flex items-center gap-2"
          style={{
            background: feedback.kind === "success" ? `${C.up}10` : `${C.down}10`,
            color: feedback.kind === "success" ? C.up : C.down,
            border: `1px solid ${feedback.kind === "success" ? C.up : C.down}30`,
            fontSize: 11,
          }}
        >
          {feedback.kind === "success" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          <span>{feedback.text}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {tab === "报告列表" && (
          <Card>
            <CardHeader
              title="历史报告"
              titleEn="Report History"
              right={<span style={{ fontSize: 10, color: C.text4 }}>{reports.length} 份报告</span>}
            />
            {loadingReports ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
            ) : errorReports ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.down }}>数据加载失败</div>
            ) : reports.length === 0 ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
            ) : (
              <div className="p-3 space-y-2">
                {reports.map((r) => (
                  <div key={r.run_id} className="flex items-center gap-4 px-4 py-3.5 rounded-xl cursor-pointer" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: C.accentSoft }}>
                      <FileText size={18} color={C.accent} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span style={{ fontSize: 13, color: C.text1, fontWeight: 500 }}>{r.name}</span>
                        <span className="px-2 py-0.5 rounded" style={{ fontSize: 9, color: C.text3, background: C.bg3 }}>
                          {r.status === "running" ? "生成中" : "完成"}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1" style={{ fontSize: 10, color: C.text4 }}>
                        <span>{fmtDate(r.created_at)}</span>
                        {r.start_date && r.end_date && <span>{fmtDate(r.start_date)} ~ {fmtDate(r.end_date)}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-4" style={{ fontSize: 11 }}>
                      {r.sharpe_ratio != null && (
                        <div className="text-right">
                          <div style={{ color: C.text4, fontSize: 9 }}>Sharpe</div>
                          <div style={{ fontFamily: C.mono, color: C.text1, fontWeight: 600 }}>{r.sharpe_ratio.toFixed(2)}</div>
                        </div>
                      )}
                      {r.annual_return != null && (
                        <div className="text-right">
                          <div style={{ color: C.text4, fontSize: 9 }}>年化</div>
                          <div style={{ fontFamily: C.mono, color: r.annual_return >= 0 ? C.up : C.down, fontWeight: 600 }}>{fmtPct(r.annual_return)}</div>
                        </div>
                      )}
                    </div>
                    {r.status === "completed" ? (
                      <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: `${C.up}10`, color: C.up, fontSize: 11, border: `1px solid ${C.up}30` }}>
                        <Download size={13} /> 下载
                      </button>
                    ) : (
                      <span className="px-3 py-1.5 rounded-lg" style={{ background: `${C.warn}10`, color: C.warn, fontSize: 11, border: `1px solid ${C.warn}30` }}>
                        生成中...
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {tab === "策略报告" && (
          <Card>
            <CardHeader
              title="策略性能报告 (iter 30+32 lifecycle)"
              titleEn="Strategy Performance Artifacts"
              right={
                <span style={{ fontSize: 10, color: C.text4 }}>
                  {strategyReports.length} 份 · sid={DEFAULT_STRATEGY_ID}
                </span>
              }
            />
            {loadingStrategyReports ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
            ) : errorStrategyReports ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.down }}>数据加载失败</div>
            ) : strategyReports.length === 0 ? (
              <div className="p-6 text-center space-y-2">
                <div style={{ fontSize: 12, color: C.text4 }}>暂无策略报告 artifact</div>
                <div style={{ fontSize: 10, color: C.text4 }}>
                  点击右上 "生成报告" 派发 Celery 任务 (iter 30 endpoint POST /api/reports/generate)
                </div>
              </div>
            ) : (
              <div className="p-3 space-y-2">
                {strategyReports.map((r) => (
                  <div
                    key={r.artifact_path}
                    className="flex items-center gap-4 px-4 py-3.5 rounded-xl"
                    style={{
                      background: r._corrupt ? `${C.down}08` : C.bg2,
                      border: `1px solid ${r._corrupt ? C.down : C.border}`,
                    }}
                  >
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center"
                      style={{ background: r._corrupt ? `${C.down}15` : C.accentSoft }}
                    >
                      {r._corrupt ? <AlertCircle size={18} color={C.down} /> : <FileText size={18} color={C.accent} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span style={{ fontSize: 13, color: C.text1, fontWeight: 500 }}>
                          {r.target_date} · {r.execution_mode}
                        </span>
                        {r._corrupt && (
                          <span className="px-2 py-0.5 rounded" style={{ fontSize: 9, color: C.down, background: `${C.down}15` }}>
                            artifact 损坏
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1" style={{ fontSize: 10, color: C.text4 }}>
                        <span>{fmtDate(r.mtime_utc)}</span>
                        {r._corrupt && r._corrupt_reason && (
                          <span style={{ color: C.down }}>{r._corrupt_reason.slice(0, 60)}</span>
                        )}
                      </div>
                    </div>
                    {r.summary && (
                      <div className="flex items-center gap-4" style={{ fontSize: 11 }}>
                        <div className="text-right">
                          <div style={{ color: C.text4, fontSize: 9 }}>Sharpe</div>
                          <div style={{ fontFamily: C.mono, color: C.text1, fontWeight: 600 }}>
                            {r.summary.sharpe.toFixed(2)}
                          </div>
                        </div>
                        <div className="text-right">
                          <div style={{ color: C.text4, fontSize: 9 }}>MDD</div>
                          <div style={{ fontFamily: C.mono, color: C.down, fontWeight: 600 }}>
                            {(r.summary.mdd * 100).toFixed(2)}%
                          </div>
                        </div>
                        <div className="text-right">
                          <div style={{ color: C.text4, fontSize: 9 }}>{r.summary.days}d 累计</div>
                          <div
                            style={{
                              fontFamily: C.mono,
                              color: r.summary.total_return >= 0 ? C.up : C.down,
                              fontWeight: 600,
                            }}
                          >
                            {fmtPct(r.summary.total_return)}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {tab === "快速统计" && (
          loadingStats ? (
            <div className="text-center py-12" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
          ) : errorStats ? (
            <div className="text-center py-12" style={{ fontSize: 12, color: C.down }}>数据加载失败</div>
          ) : !quickStats ? (
            <div className="text-center py-12" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              {periods.map(({ key, label, stats }) => (
                <Card key={key} className="p-4">
                  <div style={{ fontSize: 12, color: C.text3, marginBottom: 8 }}>{label}</div>
                  <div style={{ fontSize: 22, fontFamily: C.mono, fontWeight: 700, color: (stats?.return ?? 0) >= 0 ? C.up : C.down, marginBottom: 4 }}>
                    {fmtPct(stats?.return ?? null)}
                  </div>
                  <div className="space-y-2 mt-3">
                    {[
                      { l: "交易日数", v: stats ? String(stats.trade_days) : "—" },
                      { l: "平均换手", v: fmtPct(stats?.avg_turnover ?? null) },
                      { l: "持仓数", v: key === "today" ? String(quickStats.latest_position_count) : "—" },
                    ].map((item) => (
                      <div key={item.l} className="flex items-center justify-between" style={{ fontSize: 11 }}>
                        <span style={{ color: C.text4 }}>{item.l}</span>
                        <span style={{ fontFamily: C.mono, color: C.text1, fontWeight: 500 }}>{item.v}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          )
        )}

        {tab === "模板" && (
          <div className="grid grid-cols-2 gap-3">
            {templates.map((t) => (
              <Card key={t.name} className="p-5 cursor-pointer" style={{ border: `1px solid ${C.border}` }}>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `${t.color}15` }}>
                    <t.icon size={20} color={t.color} />
                  </div>
                  <div>
                    <div style={{ fontSize: 14, color: C.text1, fontWeight: 600 }}>{t.name}</div>
                    <div style={{ fontSize: 11, color: C.text3 }}>{t.desc}</div>
                  </div>
                </div>
                <button
                  className="w-full py-2 rounded-lg cursor-pointer disabled:opacity-50"
                  style={{ background: `${t.color}08`, color: t.color, fontSize: 11, fontWeight: 500, border: `1px solid ${t.color}20` }}
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                >
                  {generateMutation.isPending ? "派发中..." : "使用此模板生成"}
                </button>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
