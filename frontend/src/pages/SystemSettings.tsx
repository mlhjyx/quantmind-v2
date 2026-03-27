import { useParams, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";

const TABS = [
  { key: "datasource", label: "数据源" },
  { key: "notifications", label: "通知" },
  { key: "scheduler", label: "调度" },
  { key: "health", label: "健康" },
  { key: "preferences", label: "偏好" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const TAB_DESCRIPTIONS: Record<TabKey, string> = {
  datasource: "Tushare/AKShare/DeepSeek状态+积分+最后更新+测试连接+手动更新",
  notifications: "钉钉Webhook配置、P0/P1/P2级别开关、告警模板、测试发送",
  scheduler: "cron任务表（名称/频率/上次/下次/状态）+ 暂停/立即执行/查看日志",
  health: "PG/磁盘/内存/数据新鲜度/Celery/miniQMT状态卡片",
  preferences: "主题（深/浅/系统）+ 涨跌色配置 + 数据密度 + 语言 + 时区",
};

export default function SystemSettings() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const activeTab = (TABS.find((t) => t.key === tab)?.key ?? "datasource") as TabKey;

  return (
    <div>
      <Breadcrumb items={[{ label: "系统设置" }]} />
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">系统设置</h1>
        <p className="text-sm text-slate-400 mt-0.5">数据源 · 通知 · 调度 · 健康 · 偏好</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-4">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => navigate(`/settings/${t.key}`)}
            className={[
              "px-4 py-1.5 text-xs rounded-lg border transition-colors",
              t.key === activeTab
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">⚙️</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">
          {TABS.find((t) => t.key === activeTab)?.label ?? "系统设置"}
        </h2>
        <p className="text-sm text-slate-400 max-w-md">
          {TAB_DESCRIPTIONS[activeTab]}
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/system/health · GET /api/system/datasources · GET /api/system/preferences
        </p>
      </GlassCard>
    </div>
  );
}
