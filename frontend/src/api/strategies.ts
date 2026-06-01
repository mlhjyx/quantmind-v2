import apiClient from "./client";

type JsonRecord = Record<string, unknown>;

export interface Factor {
  id: string;
  name: string;
  category: string;
  ic: number;
  ir: number;
  direction: 1 | -1;
  recommended_freq: string;
  description?: string;
}

export interface Strategy {
  id: string;
  name: string;
  description?: string;
  market?: string;
  status?: string;
  active_version?: number;
  factor_ids: string[];
  top_n: number;
  rebalance_freq: "daily" | "weekly" | "monthly";
  weight_method: "equal" | "ic_weighted" | "custom";
  industry_cap: number;
  single_stock_cap: number;
  initial_capital: number;
  created_at: string;
  updated_at: string;
  sharpe?: number;
  mdd?: number;
}

export interface StrategyCreatePayload {
  name: string;
  description?: string;
  factor_ids: string[];
  top_n: number;
  rebalance_freq: "daily" | "weekly" | "monthly";
  weight_method: "equal" | "ic_weighted" | "custom";
  industry_cap: number;
  single_stock_cap: number;
  initial_capital: number;
}

export type StrategyUpdatePayload = Partial<StrategyCreatePayload>;

export interface StrategyConfigVersion {
  version: number;
  config: JsonRecord;
  changelog: string;
  created_at: string;
}

export interface StrategyDetailResponse {
  strategy: {
    id?: string;
    name?: string;
    description?: string;
    market?: string;
    mode?: string;
    factor_config?: unknown;
    backtest_config?: unknown;
    active_version?: number;
    status?: string;
    deployed_at?: string | null;
    created_at?: string;
    updated_at?: string;
  };
  active_config: StrategyConfigVersion | null;
  version_history: StrategyConfigVersion[];
}

export interface StrategyFactorInfo {
  name: string;
  category: string | null;
  direction: 1 | -1 | null;
  ic_decay_halflife: number | null;
}

export interface StrategyFactorsResponse {
  strategy_id: string;
  factor_names: string[];
  factors: StrategyFactorInfo[];
}

const DEFAULT_STRATEGY_CONFIG: StrategyCreatePayload = {
  name: "",
  description: "",
  factor_ids: [],
  top_n: 15,
  rebalance_freq: "monthly",
  weight_method: "equal",
  industry_cap: 0.25,
  single_stock_cap: 0.1,
  initial_capital: 1_000_000,
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRecord(value: unknown): JsonRecord {
  if (isRecord(value)) return value;
  if (typeof value !== "string" || !value.trim()) return {};

  try {
    const parsed: unknown = JSON.parse(value);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asRebalance(value: unknown): StrategyCreatePayload["rebalance_freq"] {
  return value === "daily" || value === "weekly" || value === "monthly" ? value : "monthly";
}

function asWeight(value: unknown): StrategyCreatePayload["weight_method"] {
  return value === "equal" || value === "ic_weighted" || value === "custom" ? value : "equal";
}

function buildStrategyConfig(payload: StrategyUpdatePayload): JsonRecord {
  const config: JsonRecord = {};
  if (payload.description !== undefined) config.description = payload.description;
  if (payload.factor_ids !== undefined) {
    config.factor_ids = payload.factor_ids;
    config.factor_names = payload.factor_ids;
  }
  if (payload.top_n !== undefined) config.top_n = payload.top_n;
  if (payload.rebalance_freq !== undefined) config.rebalance_freq = payload.rebalance_freq;
  if (payload.weight_method !== undefined) config.weight_method = payload.weight_method;
  if (payload.industry_cap !== undefined) config.industry_cap = payload.industry_cap;
  if (payload.single_stock_cap !== undefined) config.single_stock_cap = payload.single_stock_cap;
  if (payload.initial_capital !== undefined) config.initial_capital = payload.initial_capital;
  return config;
}

function strategyFromPayload(
  id: string,
  payload: StrategyUpdatePayload,
  meta: Partial<Strategy> = {},
): Strategy {
  const merged = { ...DEFAULT_STRATEGY_CONFIG, ...payload };
  return {
    id,
    name: merged.name,
    description: merged.description,
    factor_ids: merged.factor_ids,
    top_n: merged.top_n,
    rebalance_freq: merged.rebalance_freq,
    weight_method: merged.weight_method,
    industry_cap: merged.industry_cap,
    single_stock_cap: merged.single_stock_cap,
    initial_capital: merged.initial_capital,
    created_at: meta.created_at ?? "",
    updated_at: meta.updated_at ?? "",
    ...meta,
  };
}

function normalizeStrategyDetail(detail: StrategyDetailResponse): Strategy {
  const factorConfig = parseRecord(detail.strategy.factor_config);
  const backtestConfig = parseRecord(detail.strategy.backtest_config);
  const activeConfig = parseRecord(detail.active_config?.config);
  const merged = { ...factorConfig, ...backtestConfig, ...activeConfig };
  const factorIds = asStringArray(merged.factor_ids);
  const factorNames = asStringArray(merged.factor_names);

  return {
    id: asString(detail.strategy.id),
    name: asString(detail.strategy.name),
    description: asString(merged.description, detail.strategy.description),
    market: detail.strategy.market,
    status: detail.strategy.status,
    active_version: detail.strategy.active_version,
    factor_ids: factorIds.length > 0 ? factorIds : factorNames,
    top_n: asNumber(merged.top_n, DEFAULT_STRATEGY_CONFIG.top_n),
    rebalance_freq: asRebalance(merged.rebalance_freq),
    weight_method: asWeight(merged.weight_method),
    industry_cap: asNumber(merged.industry_cap, DEFAULT_STRATEGY_CONFIG.industry_cap),
    single_stock_cap: asNumber(merged.single_stock_cap, DEFAULT_STRATEGY_CONFIG.single_stock_cap),
    initial_capital: asNumber(merged.initial_capital, DEFAULT_STRATEGY_CONFIG.initial_capital),
    created_at: asString(detail.strategy.created_at),
    updated_at: asString(detail.strategy.updated_at, asString(detail.active_config?.created_at)),
  };
}

function normalizeStrategyRow(row: JsonRecord): Strategy {
  const factorConfig = parseRecord(row.factor_config);
  const factorIds = asStringArray(factorConfig.factor_ids);
  const factorNames = asStringArray(factorConfig.factor_names);
  const description = asString(factorConfig.description);
  const market = asString(row.market);
  const status = asString(row.status);

  return {
    id: asString(row.id, asString(row.strategy_id)),
    name: asString(row.name),
    description: description || undefined,
    market: market || undefined,
    status: status || undefined,
    active_version: asNumber(row.active_version, 0) || undefined,
    factor_ids: factorIds.length > 0 ? factorIds : factorNames,
    top_n: asNumber(factorConfig.top_n, DEFAULT_STRATEGY_CONFIG.top_n),
    rebalance_freq: asRebalance(factorConfig.rebalance_freq),
    weight_method: asWeight(factorConfig.weight_method),
    industry_cap: asNumber(factorConfig.industry_cap, DEFAULT_STRATEGY_CONFIG.industry_cap),
    single_stock_cap: asNumber(
      factorConfig.single_stock_cap,
      DEFAULT_STRATEGY_CONFIG.single_stock_cap,
    ),
    initial_capital: asNumber(
      factorConfig.initial_capital,
      DEFAULT_STRATEGY_CONFIG.initial_capital,
    ),
    created_at: asString(row.created_at),
    updated_at: asString(row.updated_at),
    sharpe: typeof row.sharpe === "number" ? row.sharpe : undefined,
    mdd: typeof row.mdd === "number" ? row.mdd : undefined,
  };
}

export async function listStrategies(): Promise<Strategy[]> {
  const res = await apiClient.get<JsonRecord[]>("/strategies");
  return (res.data ?? []).map(normalizeStrategyRow);
}

export async function getStrategyDetail(id: string): Promise<StrategyDetailResponse> {
  const res = await apiClient.get<StrategyDetailResponse>(`/strategies/${id}`);
  return {
    strategy: res.data.strategy ?? {},
    active_config: res.data.active_config ?? null,
    version_history: res.data.version_history ?? [],
  };
}

export async function getStrategy(id: string): Promise<Strategy> {
  return normalizeStrategyDetail(await getStrategyDetail(id));
}

export async function getStrategyVersions(id: string): Promise<StrategyConfigVersion[]> {
  const res = await apiClient.get<StrategyConfigVersion[]>(`/strategies/${id}/versions`);
  return res.data ?? [];
}

export async function getStrategyFactors(id: string): Promise<StrategyFactorsResponse> {
  const res = await apiClient.get<StrategyFactorsResponse>(`/strategies/${id}/factors`);
  return {
    strategy_id: res.data?.strategy_id ?? id,
    factor_names: res.data?.factor_names ?? [],
    factors: res.data?.factors ?? [],
  };
}

export async function createStrategy(payload: StrategyCreatePayload): Promise<Strategy> {
  const res = await apiClient.post<{ strategy_id?: string; id?: string; market?: string; status?: string }>(
    "/strategies",
    {
      name: payload.name,
      market: "astock",
      config: buildStrategyConfig(payload),
      factor_names: payload.factor_ids,
    },
  );
  const id = res.data.strategy_id ?? res.data.id ?? "";
  return strategyFromPayload(id, payload, {
    market: res.data.market ?? "astock",
    status: res.data.status ?? "draft",
  });
}

export async function updateStrategy(id: string, payload: StrategyUpdatePayload): Promise<Strategy> {
  const strategyConfig = buildStrategyConfig(payload);
  const backtestConfig = {
    ...(payload.initial_capital !== undefined ? { initial_capital: payload.initial_capital } : {}),
    ...(payload.top_n !== undefined ? { top_n: payload.top_n } : {}),
    ...(payload.rebalance_freq !== undefined ? { rebalance_freq: payload.rebalance_freq } : {}),
    ...(payload.weight_method !== undefined ? { weight_method: payload.weight_method } : {}),
  };
  const requestBody = {
    ...(payload.name !== undefined ? { name: payload.name } : {}),
    ...(Object.keys(strategyConfig).length > 0 ? { factor_config: strategyConfig } : {}),
    ...(Object.keys(backtestConfig).length > 0 ? { backtest_config: backtestConfig } : {}),
  };
  const res = await apiClient.put<{ strategy_id?: string; updated?: boolean }>(
    `/strategies/${id}`,
    requestBody,
  );
  return strategyFromPayload(res.data.strategy_id ?? id, payload);
}

export async function deleteStrategy(id: string): Promise<void> {
  await apiClient.delete(`/strategies/${id}`);
}
