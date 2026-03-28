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
}

export interface FactorsByCategory {
  [category: string]: FactorSummary[];
}

export async function getFactorsSummary(): Promise<FactorSummary[]> {
  const res = await apiClient.get<FactorSummary[]>("/factors/summary");
  return res.data;
}

export function groupFactorsByCategory(factors: FactorSummary[]): FactorsByCategory {
  return factors.reduce<FactorsByCategory>((acc, f) => {
    const cat = f.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(f);
    return acc;
  }, {});
}
