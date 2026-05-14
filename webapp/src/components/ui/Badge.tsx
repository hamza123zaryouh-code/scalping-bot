type BadgeVariant = "green" | "red" | "blue" | "yellow" | "purple" | "gray";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
}

export function Badge({ children, variant = "gray" }: BadgeProps) {
  return <span className={`badge badge-${variant}`}>{children}</span>;
}

export function LiveBadge({ active }: { active: boolean }) {
  return (
    <span className={`badge badge-${active ? "green" : "gray"}`} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span
        className={active ? "live-dot" : ""}
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: active ? "var(--accent-green)" : "var(--text-muted)",
          display: "inline-block",
        }}
      />
      {active ? "LIVE" : "OFFLINE"}
    </span>
  );
}

export function PnLBadge({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span
      className={`badge badge-${positive ? "green" : "red"}`}
    >
      {positive ? "+" : ""}{value.toFixed(2)}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: string }) {
  const variantMap: Record<string, BadgeVariant> = {
    live: "green",
    demo: "blue",
    paper: "yellow",
  };
  return <Badge variant={variantMap[mode] ?? "gray"}>{mode.toUpperCase()}</Badge>;
}
