import { Link, useLocation } from "react-router-dom";

interface BreadcrumbItem {
  label: string;
  path?: string;
}

interface BreadcrumbProps {
  items?: BreadcrumbItem[];
}

// Auto-generate from pathname if items not provided
const routeLabels: Record<string, string> = {
  dashboard: "总览",
  astock: "A股详情",
  forex: "外汇详情",
  strategy: "策略工作台",
  new: "新建策略",
  backtest: "回测分析",
  config: "回测配置",
  result: "回测结果",
  history: "策略库",
  factors: "因子库",
  compare: "因子对比",
  mining: "因子挖掘",
  tasks: "挖掘任务",
  pipeline: "AI Pipeline",
  agents: "Agent配置",
  settings: "系统设置",
};

function buildBreadcrumbs(pathname: string): BreadcrumbItem[] {
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: BreadcrumbItem[] = [{ label: "QuantMind", path: "/" }];
  let built = "";
  for (const seg of segments) {
    built += `/${seg}`;
    const label = routeLabels[seg] ?? seg;
    crumbs.push({ label, path: built });
  }
  return crumbs;
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  const { pathname } = useLocation();
  const crumbs = items ?? buildBreadcrumbs(pathname);

  if (crumbs.length <= 1) return null;

  return (
    <nav className="flex items-center gap-1.5 text-xs text-slate-400 mb-4">
      {crumbs.map((crumb, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-slate-600">/</span>}
            {isLast || !crumb.path ? (
              <span className={isLast ? "text-slate-200" : ""}>{crumb.label}</span>
            ) : (
              <Link
                to={crumb.path}
                className="hover:text-slate-200 transition-colors"
              >
                {crumb.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
