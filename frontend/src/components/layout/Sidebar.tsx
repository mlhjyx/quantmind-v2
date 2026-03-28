import { NavLink, useNavigate } from "react-router-dom";
import { NotificationPanel } from "@/components/ui/NotificationPanel";

interface NavItem {
  label: string;
  icon: string;
  path: string;
  disabled?: boolean;
}

interface NavSection {
  title?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [{ label: "总览", icon: "📊", path: "/dashboard" }],
  },
  {
    title: "策略",
    items: [
      { label: "策略工作台", icon: "⚡", path: "/strategy" },
      { label: "回测分析", icon: "🔬", path: "/backtest/config" },
    ],
  },
  {
    title: "因子",
    items: [
      { label: "因子库", icon: "🧬", path: "/factors" },
      { label: "因子挖掘", icon: "⛏️", path: "/mining" },
    ],
  },
  {
    title: "AI",
    items: [{ label: "AI闭环", icon: "🤖", path: "/pipeline" }],
  },
  {
    title: "系统",
    items: [
      { label: "PT毕业评估", icon: "📈", path: "/pt-graduation" },
      { label: "系统设置", icon: "⚙️", path: "/settings" },
    ],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const navigate = useNavigate();

  return (
    <aside
      className={[
        "flex flex-col h-full",
        "bg-[rgba(10,14,35,0.95)] backdrop-blur-xl",
        "border-r border-white/8",
        "transition-all duration-200",
        collapsed ? "w-14" : "w-[180px]",
      ].join(" ")}
    >
      {/* Logo + Bell */}
      <div className="flex items-center justify-between px-3 py-4 shrink-0">
        <div
          className="flex items-center gap-2 cursor-pointer min-w-0"
          onClick={() => navigate("/dashboard")}
        >
          <span className="text-xl shrink-0">⚡</span>
          {!collapsed && (
            <span className="text-sm font-bold text-white truncate">
              QuantMind
            </span>
          )}
        </div>
        {/* Bell icon — visible in both states */}
        <NotificationPanel />
      </div>

      {/* Market switcher */}
      {!collapsed && (
        <div className="px-3 mb-3">
          <div className="flex rounded-lg overflow-hidden border border-white/10 text-xs">
            <button className="flex-1 py-1 bg-blue-600/80 text-white font-medium">
              A股
            </button>
            <button className="flex-1 py-1 text-slate-400 hover:text-slate-200 transition-colors">
              外汇
            </button>
          </div>
        </div>
      )}

      {/* Nav sections */}
      <nav className="flex-1 overflow-y-auto px-2 space-y-1 pb-4">
        {NAV_SECTIONS.map((section, si) => (
          <div key={si}>
            {section.title && !collapsed && (
              <p className="text-[10px] text-slate-500 uppercase tracking-wider px-2 pt-3 pb-1">
                {section.title}
              </p>
            )}
            {section.title && collapsed && si > 0 && (
              <div className="border-t border-white/8 my-2" />
            )}
            {section.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-2.5 px-2 py-2 rounded-lg text-sm",
                    "transition-all duration-150",
                    isActive
                      ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent",
                    item.disabled ? "opacity-40 pointer-events-none" : "",
                  ].join(" ")
                }
              >
                <span className="text-base shrink-0">{item.icon}</span>
                {!collapsed && (
                  <span className="truncate text-xs font-medium">
                    {item.label}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer: version + status + collapse toggle */}
      <div className="shrink-0 border-t border-white/8 px-3 py-3">
        {!collapsed && (
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-2">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
            <span>v2.0 · 正常</span>
          </div>
        )}
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-center py-1 text-slate-500 hover:text-slate-300 transition-colors"
          title={collapsed ? "展开侧栏" : "收起侧栏"}
        >
          <span className="text-xs">{collapsed ? "›" : "‹"}</span>
        </button>
      </div>
    </aside>
  );
}
