import { C } from "@/theme";

interface ComingSoonProps {
  title?: string;
}

export default function ComingSoon({ title = "建设中" }: ComingSoonProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[400px] gap-4">
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl"
        style={{ background: C.accentSoft, border: `1px solid ${C.border}` }}
      >
        🔧
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, color: C.text1 }}>{title}</div>
      <div style={{ fontSize: 12, color: C.text3 }}>此页面正在开发中，敬请期待</div>
    </div>
  );
}
