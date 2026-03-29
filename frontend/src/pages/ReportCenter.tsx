import { useState } from "react";
import { FileText, Download, TrendingUp, BarChart3, Shield, Brain } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons } from "@/components/shared";
import apiClient from "@/api/client";

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

  const periods = (["today", "week", "month", "year"] as const).map((k) => ({
    key: k,
    label: PERIOD_LABELS[k],
    stats: quickStats?.[k],
  }));

  return (
    <>
      <PageHeader title="报告中心" titleEn="Report Center">
        <TabButtons tabs={["报告列表", "快速统计", "模板"]} active={tab} onChange={setTab} />
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer"
          style={{ background: C.accentSoft, color: "#a5b4fc", fontSize: 11, border: `1px solid ${C.accent}30` }}
          onClick={() => apiClient.post("/reports/generate")}
        >
          <FileText size={13} /> 生成报告
        </button>
      </PageHeader>

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
                  className="w-full py-2 rounded-lg cursor-pointer"
                  style={{ background: `${t.color}08`, color: t.color, fontSize: 11, fontWeight: 500, border: `1px solid ${t.color}20` }}
                  onClick={() => apiClient.post("/reports/generate")}
                >
                  使用此模板生成
                </button>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
