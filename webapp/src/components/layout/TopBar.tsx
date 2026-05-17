"use client";
import { usePathname } from "next/navigation";
import { LiveBadge, ModeBadge } from "../ui/Badge";
import { useWebSocket } from "../../lib/hooks/useWebSocket";

const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/dashboard/risk": "FTMO Risk Control",
  "/trading": "Live Trading",
  "/backtest": "Backtest Center",
  "/ai-memory": "AI Memory Center",
  "/optimizer": "Strategy Optimizer",
  "/analytics": "Analytics Engine",
  "/risk": "FTMO Risk Control",
  "/reports": "Reports",
};

interface TopBarProps {
  mode?: string;
  lastUpdate?: string;
}

export function TopBar({ mode = "paper", lastUpdate }: TopBarProps) {
  const pathname = usePathname();
  const title = PAGE_TITLES[pathname] ?? "Dashboard";

  const { connected } = useWebSocket({});

  const now = (() => {
    if (!lastUpdate) return new Date().toLocaleTimeString();
    const d = new Date(lastUpdate);
    return isNaN(d.getTime()) ? new Date().toLocaleTimeString() : d.toLocaleTimeString();
  })();

  return (
    <header style={{
      height: 56,
      background: "var(--bg-secondary)",
      borderBottom: "1px solid var(--border)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 24px",
      position: "sticky",
      top: 0,
      zIndex: 40,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>{title}</h1>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }} suppressHydrationWarning>
          Updated {now}
        </span>
        <ModeBadge mode={mode} />
        <LiveBadge active={connected} />
      </div>
    </header>
  );
}
