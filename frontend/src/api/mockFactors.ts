/**
 * Mock factor data — fallback when API is not connected.
 */
import type { FactorSummary, FactorLibraryStats, FactorCorrelationMatrix, FactorReport, FactorICTrend } from "./factors";

export const MOCK_FACTOR_LIBRARY: FactorSummary[] = [
  {
    id: "turnover_mean_20",
    name: "turnover_mean_20",
    category: "价量",
    ic: 0.045,
    ir: 0.62,
    direction: -1,
    recommended_freq: "月度",
    t_stat: 3.21,
    fdr_t_stat: 2.89,
    status: "active",
    gate_score: 82,
    strategy_type: "反转型",
    source: "manual",
    coverage: 0.97,
    description: "20日平均换手率，捕捉流动性反转效应",
  },
  {
    id: "volatility_20",
    name: "volatility_20",
    category: "价量",
    ic: 0.038,
    ir: 0.55,
    direction: -1,
    recommended_freq: "月度",
    t_stat: 2.95,
    fdr_t_stat: 2.61,
    status: "active",
    gate_score: 76,
    strategy_type: "低波动",
    source: "manual",
    coverage: 0.98,
    description: "20日收益率标准差，低波动溢价",
  },
  {
    id: "reversal_20",
    name: "reversal_20",
    category: "价量",
    ic: 0.041,
    ir: 0.58,
    direction: -1,
    recommended_freq: "月度",
    t_stat: 3.08,
    fdr_t_stat: 2.74,
    status: "active",
    gate_score: 79,
    strategy_type: "反转型",
    source: "manual",
    coverage: 0.99,
    description: "20日收益率反转因子",
  },
  {
    id: "amihud_20",
    name: "amihud_20",
    category: "流动性",
    ic: 0.052,
    ir: 0.71,
    direction: -1,
    recommended_freq: "月度",
    t_stat: 3.58,
    fdr_t_stat: 3.12,
    status: "active",
    gate_score: 88,
    strategy_type: "流动性溢价",
    source: "manual",
    coverage: 0.96,
    description: "Amihud非流动性指标，20日均值",
  },
  {
    id: "bp_ratio",
    name: "bp_ratio",
    category: "基本面",
    ic: 0.035,
    ir: 0.48,
    direction: 1,
    recommended_freq: "月度",
    t_stat: 2.68,
    fdr_t_stat: 2.31,
    status: "active",
    gate_score: 71,
    strategy_type: "价值型",
    source: "manual",
    coverage: 0.94,
    description: "市净率倒数（B/P），价值因子",
  },
  {
    id: "momentum_60",
    name: "momentum_60",
    category: "价量",
    ic: 0.028,
    ir: 0.41,
    direction: 1,
    recommended_freq: "月度",
    t_stat: 2.12,
    fdr_t_stat: 1.78,
    status: "degraded",
    gate_score: 52,
    strategy_type: "动量型",
    source: "manual",
    coverage: 0.98,
    description: "60日动量，近期出现衰退",
  },
  {
    id: "gp_factor_001",
    name: "gp_factor_001",
    category: "价量",
    ic: 0.031,
    ir: 0.44,
    direction: -1,
    recommended_freq: "周度",
    t_stat: 2.55,
    fdr_t_stat: 2.18,
    status: "new",
    gate_score: 65,
    strategy_type: "反转型",
    source: "gp",
    coverage: 0.95,
    description: "GP遗传编程挖掘因子，待观察",
  },
];

export const MOCK_FACTOR_STATS: FactorLibraryStats = {
  active: 5,
  new: 1,
  degraded: 1,
  retired: 2,
};

export const MOCK_FACTOR_CORRELATION: FactorCorrelationMatrix = {
  factors: ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"],
  matrix: [
    [1.00,  0.72,  0.61,  0.18, -0.05],
    [0.72,  1.00,  0.55,  0.22, -0.08],
    [0.61,  0.55,  1.00,  0.15, -0.03],
    [0.18,  0.22,  0.15,  1.00,  0.12],
    [-0.05, -0.08, -0.03,  0.12,  1.00],
  ],
};

function genDates(n: number): string[] {
  const dates: string[] = [];
  const now = new Date("2026-03-01");
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setMonth(d.getMonth() - i);
    dates.push(d.toISOString().slice(0, 7));
  }
  return dates;
}

function genIC(n: number, mean: number, std: number): number[] {
  return Array.from({ length: n }, () =>
    Number((mean + (Math.random() - 0.5) * std * 2).toFixed(4))
  );
}

export const MOCK_IC_TRENDS: FactorICTrend[] = MOCK_FACTOR_LIBRARY.slice(0, 5).map((f) => ({
  factor_id: f.id,
  factor_name: f.name,
  dates: genDates(24),
  ic_values: genIC(24, f.ic, 0.03),
}));

// ---- Full report for a single factor ----
function buildReport(f: FactorSummary): FactorReport {
  const n = 60;
  const dates = Array.from({ length: n }, (_, i) => {
    const d = new Date("2021-01-01");
    d.setMonth(d.getMonth() + i);
    return d.toISOString().slice(0, 7);
  });

  const icValues: number[] = genIC(n, f.ic, 0.04);
  let cumsum = 0;
  const icCumsum = icValues.map((v) => Number((cumsum += v).toFixed(4)));

  const groups = ["G1", "G2", "G3", "G4", "G5"];
  const annualReturns = [0.02, 0.05, 0.08, 0.12, 0.18];

  const groupDates = dates.slice(0, 24);
  const groupNav = groups.map((g, gi) => {
    let nav = 1.0;
    const navArr = groupDates.map(() => {
      nav *= 1 + ((annualReturns[gi] ?? 0.05) / 12 + (Math.random() - 0.5) * 0.02);
      return Number(nav.toFixed(4));
    });
    return { group: g, dates: groupDates, nav: navArr };
  });

  let lsNav = 1.0;
  const longshortNav = {
    dates: groupDates,
    nav: groupDates.map(() => {
      lsNav *= 1 + (0.015 / 12 + (Math.random() - 0.5) * 0.025);
      return Number(lsNav.toFixed(4));
    }),
  };

  const groupMonthly = Array.from({ length: 12 }, (_, i) => ({
    year: 2025,
    month: i + 1,
    g1: Number((Math.random() * 0.04 - 0.01).toFixed(4)),
    g2: Number((Math.random() * 0.05 - 0.01).toFixed(4)),
    g3: Number((Math.random() * 0.06 - 0.01).toFixed(4)),
    g4: Number((Math.random() * 0.07 - 0.005).toFixed(4)),
    g5: Number((Math.random() * 0.08).toFixed(4)),
    ls: Number((Math.random() * 0.04).toFixed(4)),
  }));

  const icDecay = Array.from({ length: 20 }, (_, i) => ({
    lag: i + 1,
    ic: Number((f.ic * Math.exp(-i / (f.ir * 10))).toFixed(4)),
  }));

  const correlations = [
    { name: "turnover_mean_20", corr: 0.72 },
    { name: "volatility_20", corr: 0.55 },
    { name: "reversal_20", corr: 0.61 },
    { name: "amihud_20", corr: 0.18 },
    { name: "bp_ratio", corr: -0.05 },
  ].filter((c) => c.name !== f.id);

  const industries = ["电子", "医药", "食品饮料", "银行", "地产", "汽车", "化工", "机械", "传媒", "军工"];
  const industryIC = industries.map((ind) => ({
    industry: ind,
    ic: Number((f.ic + (Math.random() - 0.5) * 0.04).toFixed(4)),
  }));

  const annualStats = [2021, 2022, 2023, 2024, 2025].map((year) => ({
    year,
    ic: Number((f.ic + (Math.random() - 0.5) * 0.02).toFixed(4)),
    ir: Number((f.ir + (Math.random() - 0.5) * 0.15).toFixed(4)),
    longshort: Number((0.12 + (Math.random() - 0.5) * 0.08).toFixed(4)),
    win_rate: Number((0.58 + (Math.random() - 0.5) * 0.1).toFixed(4)),
  }));

  const regimeStats = [
    { regime: "bull" as const, ic: Number((f.ic * 1.2).toFixed(4)), ir: Number((f.ir * 1.1).toFixed(4)), n_periods: 18 },
    { regime: "bear" as const, ic: Number((f.ic * 0.6).toFixed(4)), ir: Number((f.ir * 0.7).toFixed(4)), n_periods: 14 },
    { regime: "sideways" as const, ic: Number((f.ic * 0.9).toFixed(4)), ir: Number((f.ir * 0.95).toFixed(4)), n_periods: 28 },
  ];

  return {
    id: f.id,
    name: f.name,
    category: f.category,
    description: f.description ?? "",
    direction: f.direction,
    recommended_freq: f.recommended_freq,
    source: f.source ?? "manual",
    status: f.status,
    ic_mean: f.ic,
    ic_ir: f.ir,
    t_stat: f.t_stat,
    fdr_t_stat: f.fdr_t_stat,
    newey_west_t: Number((f.t_stat * 0.92).toFixed(4)),
    half_life_days: Math.round(20 / (f.ir * 1.5)),
    coverage: f.coverage ?? 0.96,
    gate_score: f.gate_score ?? 70,
    ic_series: dates.map((date, i) => ({ date, ic: icValues[i] ?? 0 })),
    ic_cumsum: icCumsum,
    ic_distribution: icValues,
    ic_by_period: [
      { period: "1日", ic: Number((f.ic * 0.3).toFixed(4)), ir: Number((f.ir * 0.4).toFixed(4)) },
      { period: "5日", ic: Number((f.ic * 0.7).toFixed(4)), ir: Number((f.ir * 0.75).toFixed(4)) },
      { period: "10日", ic: Number((f.ic * 0.9).toFixed(4)), ir: Number((f.ir * 0.9).toFixed(4)) },
      { period: "20日", ic: f.ic, ir: f.ir },
    ],
    group_nav: groupNav,
    longshort_nav: longshortNav,
    group_monthly: groupMonthly,
    ic_decay: icDecay,
    correlations,
    industry_ic: industryIC,
    annual_stats: annualStats,
    regime_stats: regimeStats,
  };
}

export const MOCK_FACTOR_REPORTS: Record<string, FactorReport> = Object.fromEntries(
  MOCK_FACTOR_LIBRARY.map((f) => [f.id, buildReport(f)])
);
