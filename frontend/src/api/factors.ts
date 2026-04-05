import apiClient from "./client";

export interface FactorSummary {
  id: string;
  name: string;
  category: "价量" | "流动性" | "资金流" | "基本面" | "市值" | "行业" | string;
  ic: number;
  ir: number;
  direction: 1 | -1;
  recommended_freq: string;
  t_stat: number;
  fdr_t_stat: number;
  status: "active" | "new" | "degraded" | "retired";
  description?: string;
  gate_score?: number;
  strategy_type?: string;
  source?: "manual" | "gp" | "llm" | "bruteforce";
  coverage?: number;
}

export interface FactorsByCategory {
  [category: string]: FactorSummary[];
}

// ---- Factor Library ----

export interface FactorLibraryStats {
  active: number;
  new: number;
  degraded: number;
  retired: number;
}

export interface FactorCorrelationMatrix {
  factors: string[];
  matrix: number[][];
}

export interface FactorICTrend {
  factor_id: string;
  factor_name: string;
  dates: string[];
  ic_values: number[];
}

// ---- Factor Evaluation Report ----

export interface FactorReport {
  id: string;
  name: string;
  category: string;
  description: string;
  direction: 1 | -1;
  recommended_freq: string | null;
  source: string | null;
  status: string;
  // top metrics (nullable — may not be computed yet)
  ic_mean: number | null;
  ic_ir: number | null;
  t_stat: number | null;
  fdr_t_stat: number | null;
  newey_west_t: number | null;
  half_life_days: number | null;
  coverage: number | null;
  gate_score: number | null;
  // IC analysis
  ic_series: { date: string; ic: number }[];
  ic_cumsum: number[];
  ic_distribution: number[];
  ic_by_period: { period: string; ic: number; ir: number }[];
  // Group returns
  group_nav: { group: string; dates: string[]; nav: number[] }[];
  longshort_nav: { dates: string[]; nav: number[] } | null;
  group_monthly: { year: number; month: number; g1: number; g2: number; g3: number; g4: number; g5: number; ls: number }[];
  // IC decay
  ic_decay: { lag: number; ic: number }[];
  // Correlation
  correlations: { name: string; corr: number }[];
  industry_ic: { industry: string; ic: number }[];
  // Annual stats
  annual_stats: { year: number; ic: number; ir: number; longshort: number; win_rate: number }[];
  // Market state
  regime_stats: { regime: "bull" | "bear" | "sideways"; ic: number; ir: number; n_periods: number }[];
}

/** 后端返回 ic_mean/ic_ir/gate_t，前端类型用 ic/ir/t_stat — 此处做映射 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mapFactor(raw: any): FactorSummary {
  return {
    ...raw,
    ic: raw.ic ?? raw.ic_mean ?? 0,
    ir: raw.ir ?? raw.ic_ir ?? 0,
    t_stat: raw.t_stat ?? raw.gate_t ?? 0,
    fdr_t_stat: raw.fdr_t_stat ?? 0,
    gate_score: raw.gate_score ?? 0,
  };
}

export async function getFactorsSummary(): Promise<FactorSummary[]> {
  const res = await apiClient.get<FactorSummary[]>("/factors/summary");
  return res.data.map(mapFactor);
}

export async function getFactorLibrary(): Promise<FactorSummary[]> {
  const res = await apiClient.get<FactorSummary[]>("/factors");
  return res.data.map(mapFactor);
}

export async function getFactorLibraryStats(): Promise<FactorLibraryStats> {
  const res = await apiClient.get<FactorLibraryStats>("/factors/stats");
  return res.data;
}

export async function getFactorCorrelation(): Promise<FactorCorrelationMatrix> {
  const res = await apiClient.get<FactorCorrelationMatrix>("/factors/correlation");
  return res.data;
}

export async function getFactorICTrends(): Promise<FactorICTrend[]> {
  const res = await apiClient.get<FactorICTrend[]>("/factors/health");
  return res.data;
}

export async function getFactorReport(name: string): Promise<FactorReport> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res = await apiClient.get<any>(`/factors/${name}/report`);
  const d = res.data;
  const ov = d.overview ?? {};
  const ics = d.ic_analysis?.stats ?? {};
  const icDecayRaw = d.ic_decay ?? {};

  // Map ic_series: API returns {trade_date, ic_value} → frontend expects {date, ic}
  const rawSeries: { trade_date?: string; date?: string; ic_value?: number; ic?: number }[] =
    d.ic_analysis?.ic_series ?? [];
  const icSeries = rawSeries.map((p) => ({
    date: p.date ?? p.trade_date ?? "",
    ic: p.ic ?? p.ic_value ?? 0,
  }));

  // Compute cumulative IC from series
  let cumSum = 0;
  const icCumsum = icSeries.map((p) => { cumSum += p.ic; return cumSum; });

  // IC distribution = raw IC values (for histogram)
  const icDistribution = icSeries.map((p) => p.ic);

  // Multi-period IC: compute from ic_decay where data exists
  const icByPeriod: { period: string; ic: number; ir: number }[] = [];
  for (const [k, v] of Object.entries(icDecayRaw)) {
    if (k === "note") continue;
    const entry = v as { ic_mean: number | null; ic_ir?: number | null; data_points: number };
    if (entry.ic_mean != null && entry.data_points > 0) {
      icByPeriod.push({
        period: `${k}`,
        ic: entry.ic_mean,
        ir: entry.ic_ir ?? 0,
      });
    }
  }

  return {
    id: d.factor_name ?? name,
    name: d.factor_name ?? name,
    category: ov.category ?? "",
    description: ov.description ?? "",
    direction: ov.direction ?? 1,
    recommended_freq: ics.recommended_freq ?? null,
    source: null,
    status: ov.status ?? "active",
    ic_mean: ics.ic_mean ?? null,
    ic_ir: ics.ic_ir ?? null,
    t_stat: ics.t_stat ?? null,
    fdr_t_stat: ics.fdr_t_stat ?? null,
    newey_west_t: ics.newey_west_t ?? null,
    half_life_days: ics.half_life_days ?? null,
    coverage: ics.data_points ? ics.data_points / 481 : null,
    gate_score: ics.gate_score ?? null,
    ic_series: icSeries,
    ic_cumsum: icCumsum,
    ic_distribution: icDistribution,
    ic_by_period: icByPeriod,
    group_nav: d.quintile_returns?.groups ?? [],
    longshort_nav: null,
    group_monthly: [],
    ic_decay: Object.entries(icDecayRaw)
      .filter(([k]) => k !== "note")
      .map(([k, v]) => ({ lag: parseInt(k) || 0, ic: (v as { ic_mean: number | null }).ic_mean ?? 0 })),
    correlations: d.correlations ?? [],
    industry_ic: [],
    annual_stats: [],
    regime_stats: [],
  };
}

export async function archiveFactor(name: string): Promise<void> {
  await apiClient.post(`/factors/${name}/archive`);
}

export async function triggerHealthCheck(): Promise<void> {
  await apiClient.post("/factors/health");
}

export async function triggerCorrelationPrune(): Promise<void> {
  await apiClient.post("/factors/correlation-prune");
}

export function groupFactorsByCategory(factors: FactorSummary[]): FactorsByCategory {
  return factors.reduce<FactorsByCategory>((acc, f) => {
    const cat = f.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(f);
    return acc;
  }, {});
}
