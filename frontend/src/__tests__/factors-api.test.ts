/**
 * factors.ts API 函数单元测试
 *
 * orphan O9 修复回归守门: triggerHealthCheck 必须 POST /factors/health-check。
 * 旧实现 POST /factors/health → backend 该路径仅 GET → 405。本测试锁定修正后的
 * URL，防回归。
 *
 * 使用 vitest mock 拦截 apiClient，不发真实 HTTP 请求。
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";

// Mock apiClient — factors.ts 内部 `import apiClient from "./client"` 解析到同一模块。
vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import { triggerHealthCheck } from "@/api/factors";

const post = apiClient.post as unknown as Mock;

describe("triggerHealthCheck", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs /factors/health-check (regression: not the GET-only /factors/health → 405)", async () => {
    post.mockResolvedValue({ data: { status: "completed", overall_status: "healthy" } });
    await triggerHealthCheck();

    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toBe("/factors/health-check");
  });

  it("resolves void without throwing on a successful response", async () => {
    post.mockResolvedValue({ data: { status: "completed" } });
    await expect(triggerHealthCheck()).resolves.toBeUndefined();
  });
});
