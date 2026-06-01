import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import { fetchSystemStreams, type SystemStreamsResponse } from "@/api/system";

const get = apiClient.get as unknown as Mock;

describe("fetchSystemStreams", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GETs the read-only Redis Streams status endpoint", async () => {
    const payload: SystemStreamsResponse = {
      streams: [
        {
          stream: "qm:health:check_result",
          length: 12,
          last_published_at: "2026-06-01T09:30:00+08:00",
        },
      ],
    };
    get.mockResolvedValue({ data: payload });

    const result = await fetchSystemStreams();

    expect(get).toHaveBeenCalledWith("/system/streams");
    expect(result.streams[0]).toMatchObject({
      stream: "qm:health:check_result",
      length: 12,
      last_published_at: "2026-06-01T09:30:00+08:00",
    });
  });
});
