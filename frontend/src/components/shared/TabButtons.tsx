import { C } from "@/theme";

interface TabButtonsProps {
  tabs: string[];
  active: string;
  onChange: (tab: string) => void;
}

export function TabButtons({ tabs, active, onChange }: TabButtonsProps) {
  return (
    <div
      className="flex items-center gap-1 rounded-lg p-0.5"
      style={{ background: C.bg2 }}
    >
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className="px-3 py-1.5 rounded-md cursor-pointer transition-colors"
          style={{
            fontSize: 11,
            color: t === active ? "#fff" : C.text4,
            background: t === active ? C.accent : "transparent",
            fontWeight: t === active ? 500 : 400,
            border: "none",
            outline: "none",
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
