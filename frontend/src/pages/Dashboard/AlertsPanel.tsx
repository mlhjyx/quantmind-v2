import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";

export type Alert = { level: string; color: string; title: string; desc: string; time: string };

export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  return (
    <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 320 }}>
      <CardHeader
        title="预警" titleEn="Alerts"
        right={
          <span className="w-5 h-5 rounded-full flex items-center justify-center" style={{ fontSize: 10, color: "#fff", background: C.down, fontWeight: 600 }}>
            {alerts.length}
          </span>
        }
      />
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {alerts.slice(0, 20).map((a, i) => (
          <div key={i} className="rounded-lg px-3 py-2.5 cursor-pointer" style={{ background: `${a.color}06`, border: `1px solid ${a.color}15` }}>
            <div className="flex items-center gap-2">
              <span className="shrink-0 px-1.5 py-0.5 rounded" style={{ fontSize: 9, color: a.color, fontWeight: 700, fontFamily: C.mono, background: `${a.color}12` }}>
                {a.level}
              </span>
              <span style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>{a.title}</span>
              <span className="ml-auto shrink-0" style={{ fontSize: 10, color: C.text4 }}>{a.time}</span>
            </div>
            <div style={{ fontSize: 11, color: C.text3, marginTop: 3, paddingLeft: 30 }}>{a.desc}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}
