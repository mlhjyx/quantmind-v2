/**
 * Status badge color helper — extracted iter 226 from duplicate definitions
 * in PtStatus.tsx (generic pass/warn/fail/info) + SchedulerDashboard.tsx
 * (task-status success/failed/running/skipped/never).
 *
 * Per iter 225 cross-page consistency audit + iter 226 refactor-cleaner P2-A.
 *
 * Unified union covers superset for shared usage across Wave 5 dashboards.
 * Add new cases as backend status enums grow (keep `default` fallback for
 * exhaustive guard — sibling iter 211 reviewer pattern).
 */

export function statusBadgeClasses(
  status: string | null | undefined,
): string {
  switch (status) {
    case "pass":
    case "success":
      return "bg-green-500/20 text-green-400 border border-green-500/30";
    case "warn":
    case "skipped":
    case "alert":
      return "bg-amber-500/20 text-amber-400 border border-amber-500/30";
    case "fail":
    case "failed":
      return "bg-red-500/20 text-red-400 border border-red-500/30";
    case "info":
    case "running":
      return "bg-sky-500/20 text-sky-400 border border-sky-500/30";
    case "never":
    case "disabled":
      return "bg-slate-700/40 text-slate-500 border border-slate-700";
    default:
      // Reviewer pattern (sibling iter 211): exhaustive-default guard prevents
      // silent undefined return when backend extends status enum.
      return "bg-slate-700/40 text-slate-400 border border-slate-700";
  }
}
