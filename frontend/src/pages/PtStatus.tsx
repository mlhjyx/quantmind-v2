/**
 * PtStatus.tsx — Wave 5 MVP 5.1 PT 状态 operational dashboard (read-only).
 *
 * Complementary to PTGraduation (gate metrics) + SystemSettings (config view).
 * Answers 5 operational questions:
 *   S1: Where are we in PT lifecycle? (Day X/Y + completion %)
 *   S2: What's the current trading state? (positions/cash/mode/last-trade)
 *   S3: What's the system health? (PG/Redis/Celery/Disk/Memory)
 *   S4: What's blocking PT restart? (derived checklist from S1+S2+S3)
 *   S5: What's the recent task history? (scheduler_task_log last 20 rows)
 *
 * Architecture (iter 196 design + iter 198 impl):
 * - 4 existing endpoints + 1 new (scheduler-task-log iter 197 PR #511)
 * - Frontend composition for S4 (0 new "blocker analysis" endpoint)
 * - react-query refetchInterval canonical (EnvStateBanner sibling pattern)
 * - Reuse PTGraduation status color helpers + PageSkeleton + ErrorBanner
 *
 * Design ref: docs/mvp/MVP_5_1_pt_status_page.md (iter 196)
 */

import { useQuery } from "@tanstack/react-query";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { statusBadgeClasses } from "@/utils/statusBadgeClasses";
import {
  fetchPaperTradingStatus,
  type PaperTradingStatus,
} from "@/api/dashboard";
import {
  fetchEnvState,
  fetchSystemHealth,
  fetchCalendarInfo,
  fetchSchedulerTaskLog,
  type EnvState,
  type SystemHealth,
  type CalendarInfo,
  type SchedulerTaskLogResponse,
  type SchedulerTaskLogEntry,
} from "@/api/system";

// ── Status color helpers (iter 226: statusBadgeClasses moved to shared
//    utils/statusBadgeClasses.ts per refactor-cleaner P2-A consolidation) ─────

function taskStatusBadge(status: SchedulerTaskLogEntry["status"]) {
  switch (status) {
    case "success":
      return statusBadgeClasses("pass");
    case "failed":
      return statusBadgeClasses("fail");
    case "running":
      return statusBadgeClasses("info");
    case "skipped":
      return statusBadgeClasses("warn");
    default:
      // Reviewer P3 iter 198: exhaustive-default guard — future status union member
      // additions don't silently return undefined className.
      return statusBadgeClasses("info");
  }
}

function healthBadge(ok: boolean) {
  return ok ? statusBadgeClasses("pass") : statusBadgeClasses("fail");
}

function formatMoney(value: number | undefined): string {
  if (value === undefined) return "—";
  return `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

function formatDecimal(value: number | undefined, digits = 2): string {
  if (value === undefined) return "—";
  return value.toFixed(digits);
}

function formatPercent(value: number | undefined): string {
  if (value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

// ── S1 LifecycleCard ────────────────────────────────────────────────────────

function LifecycleCard({ data }: { data: CalendarInfo | undefined }) {
  const counter = data?.pt_day_counter;
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S1 — PT 生命周期进度
      </h2>
      {!counter ? (
        <div className="text-sm text-slate-500">无 PT 日期计数器数据</div>
      ) : (
        <div>
          <div className="flex items-baseline gap-3 mb-2">
            <span className="text-2xl font-bold text-slate-100">
              {counter.label}
            </span>
            <span className="text-sm text-slate-400">
              ({counter.completion_pct.toFixed(1)}%)
            </span>
          </div>
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-500 transition-all"
              style={{ width: `${Math.min(counter.completion_pct, 100)}%` }}
            />
          </div>
          <div className="mt-2 text-xs text-slate-500">
            开始: {counter.start_date} / 今天: {counter.today}
          </div>
        </div>
      )}
    </section>
  );
}

// ── S2 TradingStateCard ─────────────────────────────────────────────────────

function TradingStateCard({
  env,
  ptStatus,
}: {
  env: EnvState | undefined;
  ptStatus: PaperTradingStatus | undefined;
}) {
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S2 — 交易状态
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="执行模式" value={env?.mode ?? "—"} />
        <Metric
          label="实盘禁用"
          value={env?.live_trading_disabled === true ? "true ✓" : "false ⚠"}
        />
        <Metric label="QMT 账户" value={env?.qmt_account_id ?? "—"} />
        <Metric label="PT Top N" value={env?.pt_top_n?.toString() ?? "—"} />
        <Metric label="PT NAV" value={formatMoney(ptStatus?.nav)} />
        <Metric label="PT 持仓数" value={ptStatus?.position_count?.toString() ?? "—"} />
        <Metric label="PT 运行日" value={ptStatus?.running_days?.toString() ?? "—"} />
        <Metric label="最新数据日" value={ptStatus?.trade_date ?? "—"} />
        <Metric label="PT Sharpe" value={formatDecimal(ptStatus?.sharpe)} />
        <Metric label="PT MDD" value={formatPercent(ptStatus?.mdd)} />
        <Metric label="累计收益" value={formatPercent(ptStatus?.total_return)} />
        <Metric
          label="毕业天数"
          value={ptStatus?.graduation_ready === true ? "已满足" : "未满足"}
        />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-950/40 rounded p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-medium text-slate-200 mt-1">{value}</div>
    </div>
  );
}

// ── S3 SystemHealthCard ─────────────────────────────────────────────────────

function SystemHealthCard({ health }: { health: SystemHealth | undefined }) {
  const services = [
    { name: "PostgreSQL", ok: health?.pg?.ok === true, latency: health?.pg?.latency_ms },
    { name: "Redis", ok: health?.redis?.ok === true, latency: health?.redis?.latency_ms },
    {
      name: "Celery",
      ok: health?.celery?.ok === true,
      latency: undefined,
    },
    { name: "Disk", ok: health?.disk?.ok === true, latency: health?.disk?.percent },
    { name: "Memory", ok: health?.memory?.ok === true, latency: health?.memory?.percent },
  ];
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S3 — 系统健康
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {services.map((s) => (
          <div key={s.name} className="bg-slate-950/40 rounded p-3">
            <div className="text-xs text-slate-500">{s.name}</div>
            <div className="mt-1.5">
              <span
                className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${healthBadge(s.ok)}`}
              >
                {s.ok ? "✓ ok" : "✗ down"}
              </span>
            </div>
            {s.latency !== undefined && s.latency !== null && (
              <div className="text-xs text-slate-500 mt-1">
                {s.name === "Disk" || s.name === "Memory"
                  ? `${s.latency}%`
                  : `${s.latency}ms`}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ── S4 RestartChecklistCard (derived from S1+S2+S3) ─────────────────────────

interface ChecklistItem {
  label: string;
  status: "pass" | "warn" | "fail";
  detail?: string;
}

function deriveChecklist(
  env: EnvState | undefined,
  health: SystemHealth | undefined,
  cal: CalendarInfo | undefined,
): ChecklistItem[] {
  const items: ChecklistItem[] = [];

  // Item 1: paper-mode + live_trading_disabled (red line check)
  if (env) {
    const safe = env.mode === "paper" && env.live_trading_disabled === true;
    items.push({
      label: "环境安全态 (paper + LIVE_TRADING_DISABLED=true)",
      status: safe ? "pass" : "fail",
      detail: `mode=${env.mode} / disabled=${env.live_trading_disabled}`,
    });
  } else {
    items.push({ label: "环境安全态", status: "warn", detail: "数据加载中" });
  }

  // Item 2: System health all-ok (5 services)
  if (health) {
    const okCount = [
      health.pg?.ok,
      health.redis?.ok,
      health.celery?.ok,
      health.disk?.ok,
      health.memory?.ok,
    ].filter(Boolean).length;
    items.push({
      label: "系统健康 (5/5 services ok)",
      status: okCount === 5 ? "pass" : okCount >= 4 ? "warn" : "fail",
      detail: `${okCount}/5 ok`,
    });
  } else {
    items.push({ label: "系统健康", status: "warn", detail: "数据加载中" });
  }

  // Item 3: PT calendar progress
  if (cal?.pt_day_counter) {
    const c = cal.pt_day_counter;
    const onTrack = c.current_day >= 0 && c.completion_pct >= 0;
    items.push({
      label: "PT 进度计数器可读",
      status: onTrack ? "pass" : "fail",
      detail: c.label,
    });
  } else {
    items.push({ label: "PT 进度计数器", status: "warn", detail: "数据加载中" });
  }

  // Item 4: PT_TOP_N reasonable (gray-out test 5)
  if (env) {
    const ok = env.pt_top_n >= 5 && env.pt_top_n <= 20;
    items.push({
      label: "PT_TOP_N 在灰度范围 [5, 20]",
      status: ok ? "pass" : "warn",
      detail: `pt_top_n=${env.pt_top_n}`,
    });
  }

  return items;
}

function RestartChecklistCard({
  env,
  health,
  cal,
}: {
  env: EnvState | undefined;
  health: SystemHealth | undefined;
  cal: CalendarInfo | undefined;
}) {
  const items = deriveChecklist(env, health, cal);
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S4 — PT 重启 checklist (前端派生)
      </h2>
      <ul className="space-y-2">
        {items.map((item) => (
          // Reviewer P1 iter 198: use stable `item.label` as key (not idx) — checklist
          // items are derived from live data; idx reuse causes incorrect DOM reuse if
          // ordering shifts between loading/success states.
          <li key={item.label} className="flex items-start gap-3">
            <span
              className={`inline-flex items-center text-xs px-2 py-0.5 rounded shrink-0 ${statusBadgeClasses(
                item.status,
              )}`}
            >
              {item.status === "pass" ? "✓" : item.status === "warn" ? "⚠" : "✗"}
            </span>
            <div className="flex-1">
              <div className="text-sm text-slate-200">{item.label}</div>
              {item.detail && (
                <div className="text-xs text-slate-500 mt-0.5">{item.detail}</div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── S5 TaskHistoryTable ─────────────────────────────────────────────────────

function TaskHistoryTable({ data }: { data: SchedulerTaskLogResponse | undefined }) {
  const tasks = data?.tasks ?? [];
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S5 — 最近任务日志 (last 20)
      </h2>
      {tasks.length === 0 ? (
        <div className="text-sm text-slate-500">无任务日志记录</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">任务名</th>
                <th className="text-left py-2 pr-3">状态</th>
                <th className="text-left py-2 pr-3">开始时间</th>
                <th className="text-right py-2 pr-3">耗时 (s)</th>
                <th className="text-left py-2">错误</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className="border-b border-slate-800/50">
                  <td className="py-2 pr-3 text-slate-300 font-mono">{t.task_name}</td>
                  <td className="py-2 pr-3">
                    <span
                      className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${taskStatusBadge(
                        t.status,
                      )}`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-400">
                    {t.start_time ?? "—"}
                  </td>
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
          <div className="text-xs text-slate-500 mt-2">
            显示 {tasks.length} / 总计 {data?.total_count ?? "—"} 行
          </div>
        </div>
      )}
    </section>
  );
}

// ── Page root ───────────────────────────────────────────────────────────────

export default function PtStatus() {
  const envQ = useQuery({
    queryKey: ["env-state"],
    queryFn: fetchEnvState,
    refetchInterval: 5_000,
  });
  const healthQ = useQuery({
    // Reviewer P1 iter 198: use page-scoped key to avoid interval-collision risk
    // with other consumers (IndustryAndSystem.tsx uses ["system-health-dash"], 30s).
    // If a future global health cache is needed, dedupe via shared module.
    queryKey: ["system-health-pt"],
    queryFn: fetchSystemHealth,
    refetchInterval: 30_000,
  });
  const calQ = useQuery({
    queryKey: ["calendar-info"],
    queryFn: fetchCalendarInfo,
    refetchInterval: 60_000,
  });
  const taskLogQ = useQuery({
    queryKey: ["scheduler-task-log", 20],
    queryFn: () => fetchSchedulerTaskLog(20),
    refetchInterval: 60_000,
  });
  const ptStatusQ = useQuery({
    queryKey: ["paper-trading-status"],
    queryFn: () => fetchPaperTradingStatus(),
    refetchInterval: 60_000,
  });

  const anyLoading =
    envQ.isLoading ||
    healthQ.isLoading ||
    calQ.isLoading ||
    taskLogQ.isLoading ||
    ptStatusQ.isLoading;
  const firstError =
    envQ.error || healthQ.error || calQ.error || taskLogQ.error || ptStatusQ.error;

  if (
    anyLoading &&
    !envQ.data &&
    !healthQ.data &&
    !calQ.data &&
    !taskLogQ.data &&
    !ptStatusQ.data
  ) {
    return <PageSkeleton />;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-100">PT 状态</h1>
        <p className="text-sm text-slate-400 mt-1">
          运维 dashboard — Wave 5 MVP 5.1 (iter 198 蓝图实施)
        </p>
      </header>

      {firstError && (
        <ErrorBanner
          message={`数据加载部分失败: ${
            // Reviewer P2 iter 198: handle non-Error throws (some queryFn may throw strings).
            firstError instanceof Error ? firstError.message : String(firstError)
          }`}
        />
      )}

      <LifecycleCard data={calQ.data} />
      <TradingStateCard env={envQ.data} ptStatus={ptStatusQ.data} />
      <SystemHealthCard health={healthQ.data} />
      <RestartChecklistCard env={envQ.data} health={healthQ.data} cal={calQ.data} />
      <TaskHistoryTable data={taskLogQ.data} />
    </div>
  );
}
