import { GlassCard } from "@/components/ui/GlassCard";

export interface MarketConfig {
  market: "astock" | "forex";
  universe: string;
  industries: string[];
  custom_stocks: string;
  estimated_count: number;
}

interface TabMarketProps {
  value: MarketConfig;
  onChange: (updates: Partial<MarketConfig>) => void;
}

const UNIVERSE_OPTIONS = [
  { value: "all", label: "全A股", count: "~5000" },
  { value: "hs300", label: "沪深300", count: "300" },
  { value: "zz500", label: "中证500", count: "500" },
  { value: "zz1000", label: "中证1000", count: "1000" },
  { value: "gem", label: "创业板", count: "~1200" },
  { value: "star", label: "科创板", count: "~500" },
  { value: "industry", label: "按行业", count: null },
  { value: "custom", label: "自定义", count: null },
];

const SW_INDUSTRIES = [
  "农林牧渔", "采掘", "化工", "钢铁", "有色金属", "电子",
  "家用电器", "食品饮料", "纺织服装", "轻工制造", "医药生物",
  "公用事业", "交通运输", "房地产", "商业贸易", "休闲服务",
  "综合", "建筑材料", "建筑装饰", "电气设备", "国防军工",
  "计算机", "传媒", "通信", "银行", "非银金融",
  "汽车", "机械设备", "仪器仪表", "信息服务", "煤炭",
];

export function TabMarket({ value, onChange }: TabMarketProps) {
  function toggleIndustry(ind: string) {
    const next = value.industries.includes(ind)
      ? value.industries.filter((x) => x !== ind)
      : [...value.industries, ind];
    onChange({ industries: next });
  }

  return (
    <div className="space-y-6">
      {/* Market selection */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">市场</label>
        <div className="flex gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="market"
              value="astock"
              checked={value.market === "astock"}
              onChange={() => onChange({ market: "astock" })}
              className="accent-blue-500"
            />
            <span className="text-sm text-slate-300">A股</span>
          </label>
          <label className="flex items-center gap-2 cursor-not-allowed opacity-40">
            <input type="radio" disabled />
            <span className="text-sm text-slate-400">外汇 (Phase 2)</span>
          </label>
        </div>
      </div>

      {/* Universe selection */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">股票池</label>
        <div className="grid grid-cols-4 gap-2">
          {UNIVERSE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onChange({ universe: opt.value })}
              className={`px-3 py-2 rounded-xl border text-xs text-left transition-colors ${
                value.universe === opt.value
                  ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                  : "border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-300"
              }`}
            >
              <div className="font-medium">{opt.label}</div>
              {opt.count && <div className="text-slate-500 mt-0.5">{opt.count}只</div>}
            </button>
          ))}
        </div>
      </div>

      {/* Industry multi-select */}
      {value.universe === "industry" && (
        <div>
          <label className="text-sm font-medium text-slate-300 block mb-3">
            选择行业 (已选 {value.industries.length})
          </label>
          <div className="flex flex-wrap gap-2">
            {SW_INDUSTRIES.map((ind) => {
              const isSelected = value.industries.includes(ind);
              return (
                <button
                  key={ind}
                  onClick={() => toggleIndustry(ind)}
                  className={`px-2.5 py-1 rounded-lg text-xs border transition-colors ${
                    isSelected
                      ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                      : "border-white/10 text-slate-400 hover:border-white/20"
                  }`}
                >
                  {ind}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Custom input */}
      {value.universe === "custom" && (
        <div>
          <label className="text-sm font-medium text-slate-300 block mb-2">
            自定义股票池
          </label>
          <textarea
            rows={4}
            placeholder="每行一个股票代码，如: 000001.SZ"
            value={value.custom_stocks}
            onChange={(e) => onChange({ custom_stocks: e.target.value })}
            className="w-full px-3 py-2 text-xs bg-white/5 border border-white/10 rounded-xl text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50 font-mono resize-none"
          />
          <p className="text-xs text-slate-500 mt-1">或上传 CSV 文件（第一列为股票代码）</p>
        </div>
      )}

      {/* Estimated count */}
      <GlassCard variant="glow" padding="sm">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">预估股票数量</span>
          <span className="text-xl font-semibold text-blue-300">
            {UNIVERSE_OPTIONS.find((o) => o.value === value.universe)?.count ??
              (value.universe === "industry" ? `~${value.industries.length * 30}` :
               value.universe === "custom" ? value.custom_stocks.split("\n").filter(Boolean).length :
               "—")}
          </span>
        </div>
      </GlassCard>
    </div>
  );
}
