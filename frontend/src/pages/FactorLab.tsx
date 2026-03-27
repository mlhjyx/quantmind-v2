import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

const MODES = ["手动编写", "表达式构建", "GP遗传编程", "LLM生成", "暴力枚举"] as const;

export default function FactorLab() {
  return (
    <div>
      <Breadcrumb items={[{ label: "因子挖掘", path: "/mining" }, { label: "因子实验室" }]} />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">因子实验室</h1>
          <p className="text-sm text-slate-400 mt-0.5">5种挖掘模式</p>
        </div>
        <Button size="sm">提交评估</Button>
      </div>

      {/* Mode tabs placeholder */}
      <div className="flex gap-1 mb-4">
        {MODES.map((m, i) => (
          <button
            key={m}
            className={[
              "px-3 py-1.5 text-xs rounded-lg border transition-colors",
              i === 0
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
            ].join(" ")}
          >
            {m}
          </button>
        ))}
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">⛏️</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">因子实验室</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：5模式Tab（手动编写/表达式构建/GP遗传编程/LLM生成/暴力枚举）、中央工作区（Monaco编辑器/拖拽构建器/参数配置）、右侧AI助手（260px）。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: POST /api/factor/mine/gp · POST /api/factor/mine/llm · POST /api/factor/mine/brute
        </p>
      </GlassCard>
    </div>
  );
}
