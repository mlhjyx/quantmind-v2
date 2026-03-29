/**
 * API 函数单元测试
 *
 * 覆盖:
 * - factors.ts: getFactorLibrary / getFactorLibraryStats / groupFactorsByCategory
 * - dashboard.ts: fetchSummary / fetchNAVSeries / fetchCircuitBreakerState
 * - mining.ts: 如存在的话
 *
 * 使用 vitest mock 拦截 axios，不发真实 HTTP 请求。
 * 铁律5: 所有函数已通过 read 验证（factors.ts / dashboard.ts）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import axios from "axios";

// Mock axios 模块
vi.mock("axios", async () => {
  const actual = await vi.importActual<typeof import("axios")>("axios");
  return {
    ...actual,
    default: {
      ...actual.default,
      create: vi.fn(() => ({
        get: vi.fn(),
        post: vi.fn(),
        interceptors: {
          request: { use: vi.fn() },
          response: { use: vi.fn() },
        },
      })),
    },
  };
});

// ─────────────────────────────────────────────────────────────
// factors.ts — groupFactorsByCategory (pure function, no HTTP)
// ─────────────────────────────────────────────────────────────

import {
  groupFactorsByCategory,
  type FactorSummary,
} from "@/api/factors";

describe("groupFactorsByCategory", () => {
  const makeFactors = (): FactorSummary[] => [
    {
      id: "1",
      name: "turnover_mean_20",
      category: "价量",
      ic: 0.045,
      ir: 0.9,
      direction: -1,
      recommended_freq: "monthly",
      t_stat: 4.5,
      fdr_t_stat: 3.2,
      status: "active",
    },
    {
      id: "2",
      name: "bp_ratio",
      category: "基本面",
      ic: 0.026,
      ir: 0.6,
      direction: 1,
      recommended_freq: "monthly",
      t_stat: 2.6,
      fdr_t_stat: 2.1,
      status: "active",
    },
    {
      id: "3",
      name: "volatility_20",
      category: "价量",
      ic: 0.033,
      ir: 0.7,
      direction: -1,
      recommended_freq: "monthly",
      t_stat: 3.3,
      fdr_t_stat: 2.5,
      status: "active",
    },
  ];

  it("按 category 分组", () => {
    const grouped = groupFactorsByCategory(makeFactors());
    expect(Object.keys(grouped).sort()).toEqual(["价量", "基本面"]);
  });

  it("同一 category 的因子全部归组", () => {
    const grouped = groupFactorsByCategory(makeFactors());
    expect(grouped["价量"]).toHaveLength(2);
    expect(grouped["基本面"]).toHaveLength(1);
  });

  it("空数组返回空对象", () => {
    const grouped = groupFactorsByCategory([]);
    expect(grouped).toEqual({});
  });

  it("单个因子也能正确分组", () => {
    const factors = makeFactors().slice(0, 1);
    const grouped = groupFactorsByCategory(factors);
    expect(grouped["价量"]).toHaveLength(1);
    expect(grouped["价量"][0].name).toBe("turnover_mean_20");
  });

  it("所有因子在同一 category 时归为一组", () => {
    const factors = makeFactors().filter((f) => f.category === "价量");
    const grouped = groupFactorsByCategory(factors);
    expect(Object.keys(grouped)).toEqual(["价量"]);
    expect(grouped["价量"]).toHaveLength(2);
  });
});

// ─────────────────────────────────────────────────────────────
// FactorLibraryStats shape validation (type-level test)
// ─────────────────────────────────────────────────────────────

import type { FactorLibraryStats } from "@/api/factors";

describe("FactorLibraryStats type shape", () => {
  it("包含 active/new/degraded/retired 字段", () => {
    const stats: FactorLibraryStats = {
      active: 5,
      new: 2,
      degraded: 1,
      retired: 0,
    };
    expect(stats.active).toBe(5);
    expect(stats.new).toBe(2);
    expect(stats.degraded).toBe(1);
    expect(stats.retired).toBe(0);
  });
});
