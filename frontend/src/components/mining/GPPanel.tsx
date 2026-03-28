import { useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { GPConfig } from "@/api/mining";

interface EvolutionPoint {
  generation: number;
  best_fitness: number;
  avg_fitness: number;
}

interface GPPanelProps {
  onStart: (config: GPConfig) => void;
  onPause?: () => void;
  onCancel?: () => void;
  isRunning?: boolean;
  isPaused?: boolean;
  submitting?: boolean;
  evolutionHistory?: EvolutionPoint[];
  currentGeneration?: number;
  totalGenerations?: number;
  bestFitness?: number;
  // list of completed GP task IDs for warm start selection
  completedTaskIds?: string[];
}

const DEFAULT_CONFIG: GPConfig = {
  population_size: 500,
  max_generations: 100,
  n_islands: 4,
  warm_start: false,
  mutation_rate: 0.2,
  crossover_rate: 0.7,
  tournament_size: 5,
  max_depth: 6,
};

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  format?: (v: number) => string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-400 w-24 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-blue-500 disabled:opacity-40"
      />
      <span className="text-xs font-mono text-slate-200 w-12 text-right">
        {format ? format(value) : value}
      </span>
    </div>
  );
}

export function GPPanel({
  onStart,
  onPause,
  onCancel,
  isRunning = false,
  isPaused = false,
  submitting = false,
  evolutionHistory = [],
  currentGeneration,
  totalGenerations,
  bestFitness,
  completedTaskIds = [],
}: GPPanelProps) {
  const [config, setConfig] = useState<GPConfig>(DEFAULT_CONFIG);

  const set = (k: keyof GPConfig, v: GPConfig[keyof GPConfig]) =>
    setConfig((prev) => ({ ...prev, [k]: v }));

  const progress =
    currentGeneration !== undefined && totalGenerations
      ? Math.round((currentGeneration / totalGenerations) * 100)
      : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Config Panel */}
      <GlassCard>
        <h3 className="text-sm font-semibold text-slate-200 mb-4">GP配置</h3>
        <div className="flex flex-col gap-3">
          <SliderRow
            label="种群大小"
            value={config.population_size}
            min={100}
            max={2000}
            step={100}
            onChange={(v) => set("population_size", v)}
            disabled={isRunning}
          />
          <SliderRow
            label="最大代数"
            value={config.max_generations}
            min={10}
            max={500}
            step={10}
            onChange={(v) => set("max_generations", v)}
            disabled={isRunning}
          />
          <SliderRow
            label="岛屿数量"
            value={config.n_islands}
            min={1}
            max={16}
            step={1}
            onChange={(v) => set("n_islands", v)}
            disabled={isRunning}
          />
          <SliderRow
            label="变异率"
            value={config.mutation_rate}
            min={0.05}
            max={0.5}
            step={0.05}
            onChange={(v) => set("mutation_rate", v)}
            disabled={isRunning}
            format={(v) => v.toFixed(2)}
          />
          <SliderRow
            label="交叉率"
            value={config.crossover_rate}
            min={0.3}
            max={0.95}
            step={0.05}
            onChange={(v) => set("crossover_rate", v)}
            disabled={isRunning}
            format={(v) => v.toFixed(2)}
          />
          <SliderRow
            label="最大深度"
            value={config.max_depth}
            min={3}
            max={10}
            step={1}
            onChange={(v) => set("max_depth", v)}
            disabled={isRunning}
          />

          {/* Warm Start */}
          <div className="flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.warm_start}
                disabled={isRunning}
                onChange={(e) => set("warm_start", e.target.checked)}
                className="accent-blue-500 w-3.5 h-3.5"
              />
              <span className="text-xs text-slate-300">Warm Start（从已有任务继续进化）</span>
            </label>
          </div>
          {config.warm_start && completedTaskIds.length > 0 && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-400 w-24 shrink-0">基础任务</span>
              <select
                value={config.warm_start_task_id ?? ""}
                disabled={isRunning}
                onChange={(e) => set("warm_start_task_id", e.target.value)}
                className="flex-1 bg-slate-800 border border-white/10 text-slate-200 text-xs rounded-lg px-2 py-1"
              >
                <option value="">选择任务...</option>
                {completedTaskIds.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="flex gap-2 mt-4">
          {!isRunning && !isPaused && (
            <Button
              size="sm"
              loading={submitting}
              onClick={() => onStart(config)}
            >
              启动进化
            </Button>
          )}
          {(isRunning || isPaused) && (
            <>
              {isRunning && (
                <Button size="sm" variant="secondary" onClick={onPause}>
                  暂停
                </Button>
              )}
              {isPaused && (
                <Button size="sm" onClick={() => onStart(config)} loading={submitting}>
                  继续
                </Button>
              )}
              <Button size="sm" variant="danger" onClick={onCancel}>
                终止
              </Button>
            </>
          )}
        </div>
      </GlassCard>

      {/* Progress */}
      {(isRunning || isPaused || evolutionHistory.length > 0) && (
        <GlassCard>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-200">进化进度</h3>
            <div className="flex items-center gap-4 text-xs text-slate-400">
              {currentGeneration !== undefined && (
                <span>
                  第 <span className="text-slate-200 font-mono">{currentGeneration}</span>
                  {totalGenerations ? ` / ${totalGenerations}` : ""} 代
                </span>
              )}
              {bestFitness !== undefined && (
                <span>
                  最优 IC_IR{" "}
                  <span className="text-green-400 font-mono">{bestFitness.toFixed(4)}</span>
                </span>
              )}
            </div>
          </div>

          {/* Progress bar */}
          {totalGenerations && (
            <div className="w-full bg-slate-800 rounded-full h-1.5 mb-4">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}

          {/* Evolution curve */}
          {evolutionHistory.length > 0 && (
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={evolutionHistory} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis
                  dataKey="generation"
                  tick={{ fill: "#7a82a6", fontSize: 10 }}
                  tickLine={false}
                  label={{ value: "代数", position: "insideBottom", offset: -2, fill: "#454d6e", fontSize: 10 }}
                />
                <YAxis
                  tick={{ fill: "#7a82a6", fontSize: 10 }}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(15,20,45,0.95)",
                    border: "1px solid rgba(100,120,200,0.2)",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "#7a82a6" }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#7a82a6" }}
                  iconType="circle"
                  iconSize={8}
                />
                <Line
                  type="monotone"
                  dataKey="best_fitness"
                  name="最优适应度"
                  stroke="#6c7eff"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="avg_fitness"
                  name="平均适应度"
                  stroke="#a78bfa"
                  strokeWidth={1.5}
                  dot={false}
                  strokeDasharray="4 2"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </GlassCard>
      )}
    </div>
  );
}
