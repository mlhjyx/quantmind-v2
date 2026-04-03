import { NavLink } from "react-router-dom";
import {
  LayoutGrid,
  Zap,
  BarChart3,
  Library,
  Database,
  Layers,
  Brain,
  TrendingUp,
  Shield,
  ArrowLeftRight,
  ShieldCheck,
  GraduationCap,
  Settings,
} from "lucide-react";
import { C } from "@/theme";
import { NotificationPanel } from "@/components/ui/NotificationPanel";

interface NavItem {
  icon: React.ElementType;
  label: string;
  path: string;
}

interface NavSection {
  group: string;
  items: NavItem[];
}

// 导航按生产使用频率组织（基于设计文档+实际运营需求）
// 高频: 总览/持仓/风控/执行（每日使用）
// 中频: 策略/回测（调仓周期使用）
// 低频: 因子/挖掘/AI/设置（研究阶段使用）
const NAV_SECTIONS: NavSection[] = [
  {
    group: "",
    items: [{ icon: LayoutGrid, label: "总览", path: "/dashboard" }],
  },
  {
    group: "交易",
    items: [
      { icon: TrendingUp, label: "持仓管理", path: "/portfolio" },
      { icon: Shield, label: "风控监控", path: "/risk" },
      { icon: ArrowLeftRight, label: "交易执行", path: "/execution" },
      { icon: ShieldCheck, label: "利润保护", path: "/pms" },
    ],
  },
  {
    group: "策略",
    items: [
      { icon: Zap, label: "策略工作台", path: "/strategy" },
      { icon: BarChart3, label: "回测分析", path: "/backtest/config" },
      { icon: Library, label: "策略库", path: "/backtest/history" },
    ],
  },
  {
    group: "因子",
    items: [
      { icon: Database, label: "因子库", path: "/factors" },
      { icon: Layers, label: "因子挖掘", path: "/mining" },
    ],
  },
  {
    group: "AI",
    items: [{ icon: Brain, label: "AI闭环", path: "/pipeline" }],
  },
  {
    group: "系统",
    items: [
      { icon: GraduationCap, label: "PT毕业评估", path: "/pt-graduation" },
      { icon: Settings, label: "系统设置", path: "/settings" },
    ],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      className="flex flex-col h-full shrink-0 transition-all duration-200"
      style={{
        width: collapsed ? 56 : 200,
        background: C.bg0,
        borderRight: `1px solid ${C.border}`,
      }}
    >
      {/* Logo + collapse toggle */}
      <div
        className="flex items-center justify-between px-3 py-3.5 shrink-0 cursor-pointer"
        onClick={onToggle}
        title={collapsed ? "展开侧栏" : "收起侧栏"}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 select-none"
            style={{
              background: `linear-gradient(135deg, ${C.accent}, #a855f7)`,
              fontSize: 14,
              fontWeight: 700,
              color: "#fff",
              boxShadow: `0 0 16px ${C.accent}50`,
            }}
          >
            Q
          </div>
          {!collapsed && (
            <span
              style={{ fontSize: 14, color: C.text1, fontWeight: 600, letterSpacing: 0.5 }}
              className="truncate"
            >
              QuantMind
            </span>
          )}
        </div>
        {/* Notification bell only visible when expanded */}
        {!collapsed && <NotificationPanel />}
      </div>

      {/* Market switcher */}
      {!collapsed && (
        <div className="mx-3 mb-3">
          <div
            className="flex rounded-md overflow-hidden"
            style={{ border: `1px solid ${C.border}` }}
          >
            <div
              className="flex-1 text-center py-1.5"
              style={{ fontSize: 10, color: "#fff", background: C.accentSoft, fontWeight: 500 }}
            >
              A股
            </div>
            <div
              className="flex-1 text-center py-1.5"
              style={{ fontSize: 10, color: C.text4 }}
            >
              外汇
            </div>
          </div>
        </div>
      )}

      {/* Nav sections */}
      <nav className="flex-1 flex flex-col gap-0.5 px-2 overflow-y-auto pb-4">
        {NAV_SECTIONS.map((section, si) => (
          <div key={si}>
            {/* Group label */}
            {section.group && !collapsed && (
              <div
                className="px-2.5 pt-4 pb-1"
                style={{
                  fontSize: 9,
                  color: C.accent,
                  letterSpacing: 2,
                  textTransform: "uppercase",
                  fontWeight: 600,
                }}
              >
                {section.group}
              </div>
            )}
            {section.group && collapsed && si > 0 && (
              <div className="my-2" style={{ borderTop: `1px solid ${C.border}` }} />
            )}

            {section.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/dashboard"}
                className="block"
                style={({ isActive }) => ({
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: 8,
                  cursor: "pointer",
                  position: "relative",
                  background: isActive ? C.accentSoft : "transparent",
                  textDecoration: "none",
                  transition: "background 150ms",
                })}
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <div
                        className="absolute left-0 top-1/2 -translate-y-1/2 rounded-r-full"
                        style={{ width: 3, height: 16, background: C.accent }}
                      />
                    )}
                    <item.icon
                      size={17}
                      color={isActive ? "#a5b4fc" : C.text4}
                      strokeWidth={isActive ? 2 : 1.5}
                    />
                    {!collapsed && (
                      <span
                        className="truncate"
                        style={{
                          fontSize: 12,
                          color: isActive ? "#c7d2fe" : C.text3,
                          fontWeight: isActive ? 500 : 400,
                        }}
                      >
                        {item.label}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div
        className="px-3 py-3 shrink-0"
        style={{ borderTop: `1px solid ${C.border}` }}
      >
        <div className="flex items-center gap-1.5" style={{ fontSize: 9, color: C.text4 }}>
          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: C.up }} />
          {!collapsed && <span>v2.0 · 在线</span>}
        </div>
      </div>
    </aside>
  );
}
