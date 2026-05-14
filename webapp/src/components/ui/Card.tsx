import React from "react";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  glow?: "green" | "red" | "blue" | "none";
  style?: React.CSSProperties;
}

export function Card({ children, className = "", title, subtitle, action, glow = "none", style }: CardProps) {
  const glowClass = glow !== "none" ? `glow-${glow}` : "";
  return (
    <div className={`card ${glowClass} ${className}`} style={style}>
      {(title || action) && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            {title && (
              <h3 style={{ fontSize: 13, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: subtitle ? 2 : 0 }}>
                {title}
              </h3>
            )}
            {subtitle && <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

interface KPICardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: "green" | "red" | "blue" | "yellow" | "purple" | "default";
  icon?: React.ReactNode;
  trend?: "up" | "down" | "neutral";
}

export function KPICard({ label, value, sub, color = "default", icon, trend }: KPICardProps) {
  const colorMap: Record<string, string> = {
    green: "var(--accent-green)",
    red: "var(--accent-red)",
    blue: "var(--accent-blue)",
    yellow: "var(--accent-yellow)",
    purple: "var(--accent-purple)",
    default: "var(--text-primary)",
  };
  const trendColor = trend === "up" ? "var(--accent-green)" : trend === "down" ? "var(--accent-red)" : "var(--text-secondary)";

  return (
    <div className="card card-hover" style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div style={{ flex: 1 }}>
          <p className="stat-label">{label}</p>
          <p className="stat-value" style={{ color: colorMap[color], marginTop: 8 }}>{value}</p>
          {sub && (
            <p className="stat-change" style={{ color: trendColor, marginTop: 4 }}>
              {trend === "up" && "▲ "}{trend === "down" && "▼ "}{sub}
            </p>
          )}
        </div>
        {icon && (
          <div style={{ color: colorMap[color], opacity: 0.7, fontSize: 22 }}>{icon}</div>
        )}
      </div>
    </div>
  );
}
