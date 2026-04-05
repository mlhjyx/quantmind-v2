import { ChevronRight } from "lucide-react";
import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";

export type PipelineStep = { name: string; status: string };

export function AIPipelinePanel({ pipelineSteps }: { pipelineSteps: PipelineStep[] }) {
  return (
    <Card className="col-span-5">
      <CardHeader
        title="AI 闭环" titleEn="Pipeline"
        right={
          <span className="px-2 py-0.5 rounded-full" style={{ fontSize: 9, color: "#a5b4fc", background: C.accentSoft, fontWeight: 500 }}>
            L1 半自动
          </span>
        }
      />
      <div className="p-3.5 space-y-3">
        {/* Pipeline steps */}
        <div className="flex items-center gap-[2px]">
          {pipelineSteps.map((s, i) => (
            <div key={i} className="flex items-center">
              <div className="px-2 py-1.5 rounded-md text-center shrink-0" style={{
                fontSize: 10, minWidth: 40,
                color:      s.status === "done" ? C.up : s.status === "running" ? "#fff" : C.text4,
                background: s.status === "done" ? `${C.up}12` : s.status === "running" ? C.accent : C.bg2,
                fontWeight: s.status === "running" ? 600 : 400,
                ...(s.status === "running" ? { boxShadow: `0 0 10px ${C.accent}40` } : {}),
              }}>{s.name}</div>
              {i < pipelineSteps.length - 1 && <ChevronRight size={10} color={C.text4} className="shrink-0 mx-[-1px]" />}
            </div>
          ))}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-4 gap-2">
          {[
            { l: "上次运行", v: "2h前" },
            { l: "下次调度", v: "03-24" },
            { l: "GP代数",   v: "47" },
            { l: "候选因子", v: "2" },
          ].map((s, i) => (
            <div key={i} className="rounded-lg p-2" style={{ background: C.bg2 }}>
              <div style={{ fontSize: 9, color: C.text4 }}>{s.l}</div>
              <div style={{ fontSize: 12, color: C.text2, fontFamily: C.mono, fontWeight: 500 }}>{s.v}</div>
            </div>
          ))}
        </div>

        {/* Pending approval */}
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <span style={{ fontSize: 11, color: C.text2, fontWeight: 500 }}>待审批</span>
            <span className="w-4 h-4 rounded-full flex items-center justify-center" style={{ background: `${C.warn}15`, fontSize: 9, color: C.warn, fontWeight: 600 }}>2</span>
          </div>
          {[
            { name: "vol_skew_20",  ic: "0.031", ir: "0.72", src: "GP" },
            { name: "cond_vol_mom", ic: "0.028", ir: "0.61", src: "LLM" },
          ].map((f, i) => (
            <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg mb-1.5" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
              <div>
                <div style={{ fontSize: 11, color: C.text2, fontFamily: C.mono }}>{f.name}</div>
                <div style={{ fontSize: 9, color: C.text4 }}>IC {f.ic} · IR {f.ir} · {f.src}</div>
              </div>
              <div className="flex gap-1.5">
                <button className="px-2 py-1 rounded-md cursor-pointer" style={{ fontSize: 10, background: `${C.up}12`, color: C.up, fontWeight: 500 }}>批准</button>
                <button className="px-2 py-1 rounded-md cursor-pointer" style={{ fontSize: 10, background: `${C.down}12`, color: C.down, fontWeight: 500 }}>拒绝</button>
              </div>
            </div>
          ))}
        </div>

        {/* Quick actions */}
        <div className="flex gap-2 flex-wrap">
          {[
            { l: "▶ 运行回测", c: C.accent },
            { l: "因子体检",   c: C.up },
            { l: "导出报告",   c: C.text3 },
            { l: "风控检查",   c: C.warn },
          ].map((a) => (
            <button key={a.l} className="px-2.5 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 10, color: a.c, background: `${a.c}08`, border: `1px solid ${a.c}20` }}>
              {a.l}
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}
