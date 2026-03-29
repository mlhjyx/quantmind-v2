// ===== GLOBAL DESIGN TOKENS =====
// Migrated from Figma Make tokens.ts with QuantMind V2 enhancements

export const C = {
  // --- Background layers ---
  bg0: "#06070d",
  bg1: "#0c0e18",
  bg2: "#121526",
  bg3: "#1a1d32",

  // --- Borders ---
  border: "#1c2040",
  borderLight: "#2a2f52",

  // --- Text hierarchy ---
  text1: "#eef0ff",
  text2: "#b0b4d0",
  text3: "#6b70a0",
  text4: "#3d4270",

  // --- Accent / brand ---
  accent: "#7c5cfc",
  accentBright: "#a78bfa",
  accentSoft: "rgba(124,92,252,0.15)",

  // --- P&L colors ---
  up: "#00e5a0",
  upGlow: "rgba(0,229,160,0.25)",
  down: "#ff5070",
  downGlow: "rgba(255,80,112,0.25)",

  // --- Status ---
  warn: "#ffb020",
  info: "#4da6ff",
  gold: "#f0c050",

  // --- Typography ---
  font: "'Inter', -apple-system, 'Noto Sans SC', sans-serif",
  mono: "'JetBrains Mono', monospace",
} as const;

// --- Glassmorphism presets ---
export const Glass = {
  card: {
    background: "rgba(12,14,24,0.7)",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    border: `1px solid ${C.border}`,
  },
  cardHover: {
    background: "rgba(18,21,38,0.85)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    border: `1px solid ${C.borderLight}`,
  },
  modal: {
    background: "rgba(10,12,20,0.92)",
    backdropFilter: "blur(24px)",
    WebkitBackdropFilter: "blur(24px)",
    border: `1px solid ${C.borderLight}`,
  },
} as const;

// --- Responsive breakpoints (px) ---
export const BP = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  "2xl": 1536,
} as const;

// --- Animation durations (ms) ---
export const Duration = {
  fast: 100,
  normal: 200,
  slow: 350,
  xslow: 500,
} as const;

// --- Spacing scale ---
export const Space = {
  px: "1px",
  0.5: "2px",
  1: "4px",
  1.5: "6px",
  2: "8px",
  2.5: "10px",
  3: "12px",
  4: "16px",
  5: "20px",
  6: "24px",
} as const;

// --- Font size scale ---
export const FontSize = {
  xs: 9,
  sm: 10,
  base: 11,
  md: 12,
  lg: 13,
  xl: 14,
  "2xl": 16,
  "3xl": 18,
  "4xl": 22,
} as const;
