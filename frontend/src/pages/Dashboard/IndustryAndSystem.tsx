import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/shared";
import { fetchSystemHealth } from "@/api/system";
import { C } from "@/theme";

export type IndustryItem = { name: string; pct: number; color: string };

export function IndustryAndSystem({ industryDist }: { industryDist: IndustryItem[] }) {
  const { data: health } = useQuery({
    queryKey: ["system-health-dash"],
    queryFn: fetchSystemHealth,
    staleTime: 30_000,
    retry: 1,
  });

  const pg      = health?.postgres;
  const redis   = health?.redis;
  const celery  = health?.celery;
  const fresh   = health?.data_freshness;
  const staleLabel = fresh
    ? fresh.days_stale === 0 ? "今日" : `${fresh.days_stale}d`
    : "—";

  const pills = [
    { l: "PG",      ok: pg     ? pg.status === "ok"     : null, s: pg?.latency_ms != null ? `${pg.latency_ms}ms` : undefined },
    { l: "Redis",   ok: redis  ? redis.status === "ok"  : null, s: redis?.latency_ms != null ? `${redis.latency_ms}ms` : undefined },
    { l: "Celery",  ok: celery ? celery.status === "ok" : null, s: celery ? `${celery.active_workers}w` : undefined },
    { l: "Tushare", ok: null  as boolean | null },
    { l: "DeepSeek",ok: null  as boolean | null, s: "¥87" },
    { l: "数据",    ok: fresh  ? fresh.days_stale <= 1   : null, s: staleLabel },
  ];

  return (
    <div className="col-span-4 flex flex-col gap-3">
      <Card className="flex-1">
        <CardHeader title="行业分布" titleEn="Industry" />
        <div className="px-3 pb-2.5 pt-1.5 space-y-2">
          {industryDist.map((ind) => (
            <div key={ind.name} className="flex items-center gap-2.5">
              <span className="shrink-0" style={{ fontSize: 11, color: C.text2, width: 52 }}>{ind.name}</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: C.bg2 }}>
                <div className="h-full rounded-full" style={{ width: `${(ind.pct / 30) * 100}%`, background: ind.color, opacity: 0.75 }} />
              </div>
              <span style={{ fontSize: 10, color: C.text3, fontFamily: C.mono, width: 32, textAlign: "right" }}>{ind.pct}%</span>
            </div>
          ))}
        </div>
      </Card>
      <Card className="p-3">
        <div className="grid grid-cols-3 gap-2">
          {pills.map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 px-2 py-1.5 rounded-md" style={{ background: C.bg2 }}>
              <span className="w-2 h-2 rounded-full shrink-0" style={{
                background: s.ok === null ? C.text4 : s.ok ? C.up : C.down,
              }} />
              <span style={{ fontSize: 10, color: C.text2 }}>{s.l}</span>
              {s.s && <span className="ml-auto" style={{ fontSize: 9, color: C.text4, fontFamily: C.mono }}>{s.s}</span>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
