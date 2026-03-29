import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import {
  fetchDataSources,
  fetchSchedulerTasks,
  fetchSystemHealth,
  fetchNotificationParams,
  saveNotificationParams,
  testNotification,
  type DataSource,
  type SchedulerTask,
  type SystemHealth,
} from "@/api/system";

// ── Shared helpers ─────────────────────────────────────────────────────────

function StatusDot({ status }: { status: "healthy" | "warning" | "error" | "unknown" | "ok" | "failed" | "success" | "running" | "never" | null }) {
  const color =
    status === "healthy" || status === "ok" || status === "success"
      ? "bg-emerald-400"
      : status === "warning" || status === "running"
        ? "bg-amber-400"
        : status === "error" || status === "failed"
          ? "bg-red-400"
          : "bg-slate-500";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} shrink-0`} />;
}

function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  const color = value >= 85 ? "bg-red-400" : value >= 65 ? "bg-amber-400" : "bg-emerald-400";
  return (
    <div className={`h-2 rounded-full bg-white/10 overflow-hidden ${className}`}>
      <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${Math.min(value, 100)}%` }} />
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">{children}</h3>;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function formatNumber(n: number | null): string {
  if (n === null) return "—";
  if (n >= 1e8) return `${(n / 1e8).toFixed(1)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(1)}万`;
  return n.toLocaleString();
}

// ── Tab 1: 数据源管理 ──────────────────────────────────────────────────────

function DataSourceTab() {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSources(await fetchDataSources());
    } catch {
      setSources([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const statusLabel: Record<string, string> = {
    healthy: "正常", warning: "警告", error: "错误", unknown: "未知",
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-14 rounded-xl bg-white/5 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <GlassCard className="text-center py-12">
        <p className="text-red-400 text-sm mb-3">{error}</p>
        <Button variant="outline" size="sm" onClick={load}>重试</Button>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-1">
        <SectionTitle>数据表状态</SectionTitle>
        <Button variant="ghost" size="sm" onClick={load}>刷新</Button>
      </div>
      <div className="space-y-2">
        {sources.map((src) => (
          <GlassCard key={src.name} padding="sm" className="flex items-center gap-3">
            <StatusDot status={src.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-100">{src.display_name}</span>
                <span className="text-xs text-slate-500 font-mono">{src.name}</span>
                {src.message && (
                  <span className="text-xs text-amber-400">{src.message}</span>
                )}
              </div>
              <div className="flex gap-4 mt-0.5 text-xs text-slate-500">
                <span>最新日期: <span className="text-slate-300">{src.latest_date ?? "—"}</span></span>
                <span>行数: <span className="text-slate-300">{formatNumber(src.row_count)}</span></span>
                <span>更新: <span className="text-slate-300">{formatDate(src.last_updated)}</span></span>
              </div>
            </div>
            <span className={[
              "text-xs px-2 py-0.5 rounded-full border",
              src.status === "healthy" ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10" :
              src.status === "warning" ? "text-amber-400 border-amber-500/30 bg-amber-500/10" :
              src.status === "error" ? "text-red-400 border-red-500/30 bg-red-500/10" :
              "text-slate-400 border-slate-600 bg-slate-700/30",
            ].join(" ")}>
              {statusLabel[src.status] ?? src.status}
            </span>
          </GlassCard>
        ))}
      </div>
      {sources.length === 0 && (
        <div className="text-center py-12 text-slate-500 text-sm">暂无数据源信息</div>
      )}
    </div>
  );
}

// ── Tab 2: 通知设置 ────────────────────────────────────────────────────────

function NotificationsTab() {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [levels, setLevels] = useState({ P0: true, P1: true, P2: true });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const params = await fetchNotificationParams();
        const map = Object.fromEntries(params.map((p) => [p.key, p.value]));
        if (map["notification.dingtalk_webhook"]) setWebhookUrl(map["notification.dingtalk_webhook"]);
        if (map["notification.dingtalk_secret"]) setWebhookSecret(map["notification.dingtalk_secret"]);
        if (map["notification.level_p0"] !== undefined) setLevels((prev) => ({ ...prev, P0: map["notification.level_p0"] !== "false" }));
        if (map["notification.level_p1"] !== undefined) setLevels((prev) => ({ ...prev, P1: map["notification.level_p1"] !== "false" }));
        if (map["notification.level_p2"] !== undefined) setLevels((prev) => ({ ...prev, P2: map["notification.level_p2"] !== "false" }));
      } catch {
        // keep defaults
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      await saveNotificationParams([
        { key: "notification.dingtalk_webhook", value: webhookUrl },
        { key: "notification.dingtalk_secret", value: webhookSecret },
        { key: "notification.level_p0", value: String(levels.P0) },
        { key: "notification.level_p1", value: String(levels.P1) },
        { key: "notification.level_p2", value: String(levels.P2) },
      ]);
      setSaveMsg("已保存");
    } catch {
      setSaveMsg("保存失败，请重试");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
    }
  };

  const handleTest = async () => {
    if (!webhookUrl) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testNotification(webhookUrl);
      setTestResult(result);
    } catch {
      setTestResult({ success: false, message: "请求失败，请检查网络或Webhook地址" });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-12 rounded-xl bg-white/5 animate-pulse" />)}</div>;
  }

  return (
    <div className="space-y-6 max-w-xl">
      <GlassCard>
        <SectionTitle>钉钉通知配置</SectionTitle>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Webhook URL</label>
            <input
              type="url"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500/50 focus:bg-white/8"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">加签Secret（可选）</label>
            <input
              type="password"
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
              placeholder="SEC..."
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500/50"
            />
          </div>
          <div className="flex gap-2 items-center pt-1">
            <Button variant="outline" size="sm" onClick={handleTest} loading={testing} disabled={!webhookUrl}>
              发送测试消息
            </Button>
            {testResult && (
              <span className={`text-xs ${testResult.success ? "text-emerald-400" : "text-red-400"}`}>
                {testResult.success ? "发送成功" : testResult.message}
              </span>
            )}
          </div>
        </div>
      </GlassCard>

      <GlassCard>
        <SectionTitle>通知级别开关</SectionTitle>
        <div className="space-y-3">
          {(["P0", "P1", "P2"] as const).map((level) => {
            const info = {
              P0: { label: "P0 紧急", desc: "系统故障 / 风控熔断 / 数据异常", color: "text-red-400" },
              P1: { label: "P1 重要", desc: "因子衰退 / 净值预警 / 冷却期", color: "text-amber-400" },
              P2: { label: "P2 通知", desc: "审批待处理 / 回测完成 / 闭环完成", color: "text-blue-400" },
            }[level];
            return (
              <div key={level} className="flex items-center justify-between">
                <div>
                  <span className={`text-sm font-medium ${info.color}`}>{info.label}</span>
                  <p className="text-xs text-slate-500 mt-0.5">{info.desc}</p>
                </div>
                <button
                  onClick={() => setLevels((prev) => ({ ...prev, [level]: !prev[level] }))}
                  className={[
                    "w-10 h-5 rounded-full border transition-all duration-200 relative shrink-0",
                    levels[level]
                      ? "bg-blue-600/60 border-blue-500/50"
                      : "bg-white/10 border-white/10",
                  ].join(" ")}
                  aria-checked={levels[level]}
                  role="switch"
                >
                  <span className={[
                    "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all duration-200",
                    levels[level] ? "left-5" : "left-0.5",
                  ].join(" ")} />
                </button>
              </div>
            );
          })}
        </div>
      </GlassCard>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} loading={saving}>保存配置</Button>
        {saveMsg && (
          <span className={`text-xs ${saveMsg === "已保存" ? "text-emerald-400" : "text-red-400"}`}>
            {saveMsg}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Tab 3: 调度管理 ────────────────────────────────────────────────────────

function SchedulerTab() {
  const [tasks, setTasks] = useState<SchedulerTask[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchSchedulerTasks();
      setTasks(Array.isArray(result) ? result : []);
    } catch {
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const statusLabel: Record<string, string> = {
    success: "成功", failed: "失败", running: "运行中", never: "从未运行",
  };

  if (loading) {
    return <div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-16 rounded-xl bg-white/5 animate-pulse" />)}</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-1">
        <SectionTitle>Task Scheduler 任务</SectionTitle>
        <Button variant="ghost" size="sm" onClick={load}>刷新</Button>
      </div>
      <div className="space-y-2">
        {tasks.map((task) => (
          <GlassCard key={task.name} padding="sm" className="flex items-center gap-3">
            <StatusDot status={task.last_status ?? "unknown"} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-slate-100">{task.display_name}</span>
                <span className="text-xs text-slate-500 font-mono">{task.name}</span>
                {!task.enabled && (
                  <span className="text-xs text-slate-500 border border-slate-600 px-1.5 rounded">已禁用</span>
                )}
              </div>
              <div className="flex gap-4 mt-0.5 text-xs text-slate-500 flex-wrap">
                <span>计划: <span className="text-slate-300">{task.schedule}</span></span>
                <span>上次: <span className="text-slate-300">{formatDate(task.last_run)}</span></span>
                <span>下次: <span className="text-slate-300">{formatDate(task.next_run)}</span></span>
              </div>
            </div>
            {task.last_status && (
              <span className={[
                "text-xs px-2 py-0.5 rounded-full border shrink-0",
                task.last_status === "success" ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10" :
                task.last_status === "failed" ? "text-red-400 border-red-500/30 bg-red-500/10" :
                task.last_status === "running" ? "text-amber-400 border-amber-500/30 bg-amber-500/10" :
                "text-slate-400 border-slate-600 bg-slate-700/30",
              ].join(" ")}>
                {statusLabel[task.last_status] ?? task.last_status}
              </span>
            )}
          </GlassCard>
        ))}
      </div>
      {tasks.length === 0 && (
        <div className="text-center py-12 text-slate-500 text-sm">暂无调度任务</div>
      )}
    </div>
  );
}

// ── Tab 4: 系统健康 ────────────────────────────────────────────────────────

function HealthTab() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    // Don't show skeleton on background refresh
    try {
      setError(null);
      const data = await fetchSystemHealth();
      setHealth(data);
    } catch {
      if (!health) setError("系统健康数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [health]);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 30_000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return <div className="grid grid-cols-2 gap-3">{[...Array(6)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-white/5 animate-pulse" />)}</div>;
  }

  if (!health) {
    return (
      <GlassCard className="text-center py-12">
        <p className="text-red-400 text-sm mb-3">{error ?? "无法获取系统状态"}</p>
        <Button variant="outline" size="sm" onClick={load}>重试</Button>
      </GlassCard>
    );
  }

  const pg = health.postgres ?? { ok: false, latency_ms: null };
  const rd = health.redis ?? { ok: false, latency_ms: null };
  const cel = health.celery ?? { ok: false, active_workers: 0 };
  const services = [
    { label: "PostgreSQL", ...pg, extra: pg.latency_ms != null ? `${pg.latency_ms}ms` : undefined },
    { label: "Redis", ...rd, extra: rd.latency_ms != null ? `${rd.latency_ms}ms` : undefined },
    { label: "Celery", ...cel, extra: `${cel.active_workers ?? 0} 个 worker` },
  ];

  const staleDays = health.data_freshness?.days_stale ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between mb-1">
        <SectionTitle>服务连接</SectionTitle>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">30s 自动刷新</span>
          <Button variant="ghost" size="sm" onClick={load}>刷新</Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {services.map((svc) => (
          <GlassCard key={svc.label} padding="sm" className="flex items-center gap-3">
            <StatusDot status={svc.status} />
            <div>
              <div className="text-sm font-medium text-slate-100">{svc.label}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {svc.status === "ok" ? (
                  <span className="text-emerald-400">{svc.extra ?? "正常"}</span>
                ) : (
                  <span className="text-red-400">{svc.message ?? "连接失败"}</span>
                )}
              </div>
            </div>
          </GlassCard>
        ))}
      </div>

      <SectionTitle>资源使用</SectionTitle>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <GlassCard padding="sm">
          <div className="flex justify-between text-xs mb-2">
            <span className="text-slate-400">磁盘</span>
            <span className="text-slate-200 font-mono">
              {health.disk?.used_gb ?? "—"}GB / {health.disk?.total_gb ?? "—"}GB
            </span>
          </div>
          <ProgressBar value={health.disk?.percent ?? 0} />
          <div className="text-xs text-slate-500 mt-1 text-right">{(health.disk?.percent ?? 0).toFixed(1)}%</div>
        </GlassCard>

        <GlassCard padding="sm">
          <div className="flex justify-between text-xs mb-2">
            <span className="text-slate-400">内存</span>
            <span className="text-slate-200 font-mono">
              {(health.memory?.used_gb ?? 0).toFixed(1)}GB / {health.memory?.total_gb ?? "—"}GB
            </span>
          </div>
          <ProgressBar value={health.memory?.percent ?? 0} />
          <div className="text-xs text-slate-500 mt-1 text-right">{(health.memory?.percent ?? 0).toFixed(1)}%</div>
        </GlassCard>
      </div>

      <SectionTitle>数据新鲜度</SectionTitle>
      <GlassCard padding="sm" className="flex items-center gap-3">
        <StatusDot status={staleDays === 0 ? "healthy" : staleDays <= 1 ? "warning" : "error"} />
        <div className="flex-1">
          <span className="text-sm text-slate-100">最新K线日期</span>
          <span className="ml-3 text-sm font-mono text-slate-300">
            {health.data_freshness?.latest_kline_date ?? "—"}
          </span>
        </div>
        {staleDays > 0 && (
          <span className="text-xs text-amber-400">延迟 {staleDays} 天</span>
        )}
        {staleDays === 0 && (
          <span className="text-xs text-emerald-400">最新</span>
        )}
      </GlassCard>
    </div>
  );
}

// ── Tab 5: 用户偏好 ────────────────────────────────────────────────────────

type ColorMode = "cn" | "intl";
type Timezone = "Asia/Shanghai" | "UTC" | "America/New_York";

function PreferencesTab() {
  const [colorMode, setColorMode] = useState<ColorMode>(() => {
    return (localStorage.getItem("pref_color_mode") as ColorMode) ?? "cn";
  });
  const [timezone, setTimezone] = useState<Timezone>(() => {
    return (localStorage.getItem("pref_timezone") as Timezone) ?? "Asia/Shanghai";
  });
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    localStorage.setItem("pref_color_mode", colorMode);
    localStorage.setItem("pref_timezone", timezone);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-xl">
      <GlassCard>
        <SectionTitle>涨跌色配置</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
          {(["cn", "intl"] as const).map((mode) => {
            const info = {
              cn: { label: "A股惯例（默认）", desc: "涨红 / 跌绿", up: "text-red-400", down: "text-emerald-400" },
              intl: { label: "国际惯例", desc: "涨绿 / 跌红", up: "text-emerald-400", down: "text-red-400" },
            }[mode];
            return (
              <GlassCard
                key={mode}
                variant={colorMode === mode ? "selected" : "clickable"}
                padding="sm"
                onClick={() => setColorMode(mode)}
              >
                <div className="text-sm font-medium text-slate-100 mb-1">{info.label}</div>
                <div className="flex gap-3 text-xs">
                  <span className={info.up}>涨 +5.2%</span>
                  <span className={info.down}>跌 -3.1%</span>
                </div>
                <div className="text-xs text-slate-500 mt-1">{info.desc}</div>
              </GlassCard>
            );
          })}
        </div>
      </GlassCard>

      <GlassCard>
        <SectionTitle>时区</SectionTitle>
        <div className="space-y-2">
          {([
            { value: "Asia/Shanghai", label: "Asia/Shanghai (UTC+8)", desc: "北京时间" },
            { value: "UTC", label: "UTC+0", desc: "协调世界时" },
            { value: "America/New_York", label: "America/New_York (UTC-5/4)", desc: "美东时间" },
          ] as const).map((tz) => (
            <label key={tz.value} className="flex items-center gap-3 cursor-pointer group">
              <div className={[
                "w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
                timezone === tz.value ? "border-blue-500 bg-blue-500" : "border-slate-600 group-hover:border-slate-400",
              ].join(" ")}>
                {timezone === tz.value && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
              </div>
              <div>
                <div className="text-sm text-slate-100">{tz.label}</div>
                <div className="text-xs text-slate-500">{tz.desc}</div>
              </div>
              <input
                type="radio"
                name="timezone"
                value={tz.value}
                checked={timezone === tz.value}
                onChange={() => setTimezone(tz.value)}
                className="sr-only"
              />
            </label>
          ))}
        </div>
      </GlassCard>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave}>保存偏好</Button>
        {saved && <span className="text-xs text-emerald-400">已保存到本地</span>}
        <span className="text-xs text-slate-500">（偏好存储在浏览器本地）</span>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

const TABS = [
  { key: "datasource", label: "数据源" },
  { key: "notifications", label: "通知" },
  { key: "scheduler", label: "调度" },
  { key: "health", label: "系统健康" },
  { key: "preferences", label: "偏好" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const TAB_COMPONENTS: Record<TabKey, React.ComponentType> = {
  datasource: DataSourceTab,
  notifications: NotificationsTab,
  scheduler: SchedulerTab,
  health: HealthTab,
  preferences: PreferencesTab,
};

export default function SystemSettings() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const activeTab = (TABS.find((t) => t.key === tab)?.key ?? "datasource") as TabKey;

  const TabContent = TAB_COMPONENTS[activeTab];

  return (
    <div>
      <Breadcrumb items={[{ label: "系统设置" }]} />
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-white">系统设置</h1>
        <p className="text-sm text-slate-400 mt-0.5">数据源 · 通知 · 调度 · 健康 · 偏好</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-5 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => navigate(`/settings/${t.key}`)}
            className={[
              "px-4 py-1.5 text-xs rounded-lg border transition-colors",
              t.key === activeTab
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      <TabContent />
    </div>
  );
}
