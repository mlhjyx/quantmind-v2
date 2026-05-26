/**
 * SchedulerDashboard.tsx — Wave 5 MVP 5.5 调度任务 Dashboard (sibling MVP 5.1-5.3).
 *
 * Consolidates scheduling visibility into single page:
 *   S1: Health summary (tasks today / failed today / overdue derived)
 *   S2: Windows schtask QM-* list (from fixed fetchSchedulerTasks)
 *   S3: Celery Beat schedule (from new /api/system/beat-schedule)
 *   S4: Recent scheduler_task_log execution history (last 50 rows + filter)
 *   S5: Per-task drill-down (click → ECharts duration trend + error log)
 *
 * Architecture (iter 209 design):
 * - 2 existing endpoints + 1 new (beat-schedule iter 210)
 * - §v9.49 #11 fixed iter 210 (fetchSchedulerTasks wrapper type drift)
 *
 * Design ref: docs/mvp/MVP_5_5_scheduler_dashboard.md (iter 209)
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { statusBadgeClasses } from "@/utils/statusBadgeClasses";
import {
  fetchSchedulerTasks,
  fetchBeatSchedule,
  fetchSchedulerTaskLog,
  type SchedulerTask,
  type BeatScheduleEntry,
  type SchedulerTaskLogEntry,
} from "@/api/system";

// ── Status color helpers (iter 226: statusBadgeClasses moved to shared
//    utils/statusBadgeClasses.ts per refactor-cleaner P2-A consolidation) ─────

// ── S1 HealthSummary (derived) ─────────────────────────────────────────────

function HealthSummary({
  schtasks,
  taskLog,
}: {
  schtasks: SchedulerTask[];
  taskLog: SchedulerTaskLogEntry[];
}) {
  // Reviewer P2 iter 211 (铁律 41): use Asia/Shanghai timezone for "today",
  // not UTC. Previous `new Date().toISOString().slice(0,10)` returned UTC date,
  // causing 0 counters during 00:00-08:00 CST since UTC = yesterday.
  // 'sv' locale returns YYYY-MM-DD format.
  const today = new Date().toLocaleDateString("sv", { timeZone: "Asia/Shanghai" });
  const todayCount = taskLog.filter((t) => (t.start_time ?? "").startsWith(today)).length;
  const failedCount = taskLog.filter(
    (t) => t.status === "failed" && (t.start_time ?? "").startsWith(today),
  ).length;
  const overdueCount = schtasks.filter((t) => {
    if (!t.next_run) return false;
    try {
      return new Date(t.next_run) < new Date();
    } catch {
      return false;
    }
  }).length;
  const items = [
    { label: "今日触发", value: todayCount, color: "text-sky-400" },
    { label: "今日失败", value: failedCount, color: failedCount > 0 ? "text-red-400" : "text-green-400" },
    { label: "schtask 已过期", value: overdueCount, color: overdueCount > 0 ? "text-amber-400" : "text-green-400" },
  ];
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S1 — 调度健康
      </h2>
      <div className="grid grid-cols-3 gap-3">
        {items.map((it) => (
          <div key={it.label} className="bg-slate-950/40 rounded p-3">
            <div className="text-xs text-slate-500">{it.label}</div>
            <div className={`text-2xl font-bold mt-1 ${it.color}`}>{it.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── S2 SchtaskListSection ──────────────────────────────────────────────────

function SchtaskListSection({
  data,
  error,
  onSelectTask,
}: {
  data: SchedulerTask[];
  error: unknown;
  onSelectTask: (name: string) => void;
}) {
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S2 — Windows schtask QM-* ({data.length})
      </h2>
      {error ? (
        <div className="text-sm text-red-400 mb-3">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : null}
      {data.length === 0 ? (
        <div className="text-sm text-slate-500">无 QM-* 任务记录</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {data.map((t) => (
            <button
              key={t.name}
              onClick={() => onSelectTask(t.name)}
              className="text-left bg-slate-950/40 rounded p-3 hover:bg-slate-950/70 transition-colors"
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${statusBadgeClasses(t.last_status)}`}
                >
                  {t.last_status ?? "—"}
                </span>
                <span className="font-mono text-sm text-slate-200 truncate flex-1">
                  {t.name}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                最后运行: {t.last_run ?? "—"}
              </div>
              <div className="text-xs text-slate-500">
                下次运行: {t.next_run ?? "—"}
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

// ── S3 BeatScheduleSection ─────────────────────────────────────────────────

function BeatScheduleSection({
  entries,
  error,
  onSelectTask,
}: {
  entries: BeatScheduleEntry[];
  error: unknown;
  onSelectTask: (name: string) => void;
}) {
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S3 — Celery Beat schedule ({entries.length} entries)
      </h2>
      {error ? (
        <div className="text-sm text-red-400 mb-3">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : null}
      {entries.length === 0 ? (
        <div className="text-sm text-slate-500">无 Beat schedule entries</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">beat_key</th>
                <th className="text-left py-2 pr-3">task_name</th>
                <th className="text-left py-2 pr-3">schedule</th>
                <th className="text-left py-2 pr-3">最后触发</th>
                <th className="text-left py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr
                  key={e.beat_key}
                  onClick={() => onSelectTask(e.task_name)}
                  // Reviewer P2 iter 211: keyboard a11y for interactive table rows
                  tabIndex={0}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      onSelectTask(e.task_name);
                    }
                  }}
                  className="border-b border-slate-800/50 cursor-pointer hover:bg-slate-950/40 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-400"
                >
                  <td className="py-2 pr-3 text-slate-300 font-mono">{e.beat_key}</td>
                  <td className="py-2 pr-3 text-slate-400 font-mono text-[10px]">
                    {e.task_name}
                  </td>
                  <td className="py-2 pr-3 text-slate-500 text-[10px]">
                    {e.schedule_display.slice(0, 40)}
                  </td>
                  <td className="py-2 pr-3 text-slate-400">
                    {e.last_fire_time ?? "—"}
                  </td>
                  <td className="py-2">
                    <span
                      className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${statusBadgeClasses(e.last_fire_status)}`}
                    >
                      {e.last_fire_status ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── S4 RecentHistoryTable ──────────────────────────────────────────────────

function RecentHistoryTable({
  data,
  error,
  filter,
  onFilterChange,
  onSelectTask,
}: {
  data: SchedulerTaskLogEntry[];
  error: unknown;
  filter: string;
  onFilterChange: (next: string) => void;
  onSelectTask: (name: string) => void;
}) {
  const distinctTasks = useMemo(
    () => Array.from(new Set(data.map((t) => t.task_name))).sort(),
    [data],
  );
  const filtered = filter ? data.filter((t) => t.task_name === filter) : data;
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3 gap-3">
        <h2 className="text-base font-semibold text-slate-100">
          S4 — 最近执行历史 ({filtered.length})
        </h2>
        <select
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700"
        >
          <option value="">全部任务</option>
          {distinctTasks.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      {error ? (
        <div className="text-sm text-red-400 mb-3">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <div className="text-sm text-slate-500">无执行历史</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">任务</th>
                <th className="text-left py-2 pr-3">状态</th>
                <th className="text-left py-2 pr-3">开始时间</th>
                <th className="text-right py-2 pr-3">耗时 (s)</th>
                <th className="text-left py-2">错误</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 50).map((t) => (
                <tr
                  key={t.id}
                  onClick={() => onSelectTask(t.task_name)}
                  // Reviewer P2 iter 211: keyboard a11y for interactive table rows
                  tabIndex={0}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      onSelectTask(t.task_name);
                    }
                  }}
                  className="border-b border-slate-800/50 cursor-pointer hover:bg-slate-950/40 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-400"
                >
                  <td className="py-2 pr-3 text-slate-300 font-mono">{t.task_name}</td>
                  <td className="py-2 pr-3">
                    <span
                      className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${statusBadgeClasses(t.status)}`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-400">{t.start_time ?? "—"}</td>
                  <td className="py-2 pr-3 text-right text-slate-400">
                    {t.duration_sec ?? "—"}
                  </td>
                  <td className="py-2 text-red-400 max-w-md truncate">
                    {t.error_message ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── S5 TaskDrillDown (ECharts duration trend) ──────────────────────────────

function TaskDrillDown({ taskName, onClose }: { taskName: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["scheduler-dashboard", "drilldown", taskName],
    queryFn: () => fetchSchedulerTaskLog(20, taskName),
    enabled: !!taskName,
  });

  const tasks = data?.tasks ?? [];
  const failures = tasks.filter((t) => t.status === "failed" && t.error_message);

  const durationOption = useMemo(() => {
    // Reviewer P1 iter 211: pre-compute per-datum color array embedded in series
    // data items (vs closure callback over `tasks` indexed by params.dataIndex).
    // Old pattern was fail-soft silent if ECharts called with non-sequential index.
    // Now: each bar's color is explicit per data point at construction time.
    const chronological = [...tasks].reverse(); // oldest → newest for x-axis time order
    const seriesData = chronological.map((t) => ({
      value: t.duration_sec ?? 0,
      itemStyle: {
        color: t.status === "failed" ? "#ef4444" : "#22c55e",
      },
    }));
    return {
      grid: { left: 50, right: 20, top: 20, bottom: 40 },
      xAxis: {
        type: "category",
        data: chronological.map((t) => t.start_time?.slice(11, 19) ?? "—"),
        axisLabel: { color: "#94a3b8", fontSize: 9, rotate: 45 },
      },
      yAxis: {
        type: "value",
        name: "秒",
        nameTextStyle: { color: "#94a3b8" },
        axisLabel: { color: "#94a3b8", fontSize: 10 },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      tooltip: { trigger: "axis" },
      series: [
        {
          name: "duration",
          type: "bar",
          data: seriesData,
        },
      ],
    };
  }, [tasks]);

  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-slate-100">
          S5 — 任务详情: <span className="font-mono text-sky-400">{taskName}</span>
        </h2>
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded border border-slate-700"
        >
          关闭
        </button>
      </div>
      {error ? (
        <div className="text-sm text-red-400">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : isLoading ? (
        <div className="text-sm text-slate-500">加载中...</div>
      ) : tasks.length === 0 ? (
        <div className="text-sm text-slate-500">该任务无最近执行记录</div>
      ) : (
        <>
          <div className="mb-3">
            <div className="text-xs text-slate-500 mb-2">最近 {tasks.length} 次执行耗时趋势</div>
            <ReactECharts
              option={durationOption}
              style={{ height: "180px" }}
              opts={{ renderer: "canvas" }}
            />
          </div>
          {failures.length > 0 && (
            <div>
              <div className="text-xs text-slate-500 mb-2">
                最近错误 ({failures.length})
              </div>
              <ul className="space-y-1">
                {failures.slice(0, 5).map((t) => (
                  <li key={t.id} className="text-xs">
                    <span className="text-slate-500">{t.start_time ?? "—"}:</span>{" "}
                    <span className="text-red-400 break-all">{t.error_message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ── Page root ───────────────────────────────────────────────────────────────

export default function SchedulerDashboard() {
  const [filter, setFilter] = useState<string>("");
  const [selectedTask, setSelectedTask] = useState<string>("");

  // Reviewer P1 iter 211: clear filter when selectedTask changes via click on
  // S2/S3/S4. Without this, S4 dropdown shows stale filter while S5 drill-down
  // shows a different task — inconsistent visual state.
  function handleSelectTask(name: string) {
    setSelectedTask(name);
    setFilter("");
  }

  const schtaskQ = useQuery({
    queryKey: ["scheduler-dashboard", "schtask"],
    queryFn: fetchSchedulerTasks,
    refetchInterval: 60_000,
  });
  const beatQ = useQuery({
    queryKey: ["scheduler-dashboard", "beat"],
    queryFn: fetchBeatSchedule,
    refetchInterval: 60_000,
  });
  const logQ = useQuery({
    queryKey: ["scheduler-dashboard", "log"],
    queryFn: () => fetchSchedulerTaskLog(50),
    refetchInterval: 60_000,
  });

  const schtasks = schtaskQ.data ?? [];
  const beatEntries = beatQ.data?.entries ?? [];
  const taskLog = logQ.data?.tasks ?? [];

  if (schtaskQ.isLoading && beatQ.isLoading && logQ.isLoading) {
    return <PageSkeleton />;
  }

  const firstError = schtaskQ.error || beatQ.error || logQ.error;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-100">调度 Dashboard</h1>
        <p className="text-sm text-slate-400 mt-1">
          schtask + Celery Beat 调度监控 — Wave 5 MVP 5.5 (iter 211 蓝图实施)
        </p>
      </header>

      {firstError && (
        <ErrorBanner
          message={`调度数据加载部分失败: ${firstError instanceof Error ? firstError.message : "unknown"}`}
        />
      )}

      <HealthSummary schtasks={schtasks} taskLog={taskLog} />
      <SchtaskListSection
        data={schtasks}
        error={schtaskQ.error}
        onSelectTask={handleSelectTask}
      />
      <BeatScheduleSection
        entries={beatEntries}
        error={beatQ.error}
        onSelectTask={handleSelectTask}
      />
      <RecentHistoryTable
        data={taskLog}
        error={logQ.error}
        filter={filter}
        onFilterChange={setFilter}
        onSelectTask={handleSelectTask}
      />
      {selectedTask && (
        <TaskDrillDown taskName={selectedTask} onClose={() => setSelectedTask("")} />
      )}
    </div>
  );
}
