"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: "⬡" },
  { href: "/trading", label: "Live Trading", icon: "◈" },
  { href: "/backtest", label: "Backtest Center", icon: "⊡" },
  { href: "/ai-memory", label: "AI Memory", icon: "◎" },
  { href: "/optimizer", label: "Optimizer", icon: "⊕" },
  { href: "/analytics", label: "Analytics", icon: "◉" },
  { href: "/risk", label: "FTMO Risk", icon: "◬" },
  { href: "/reports", label: "Reports", icon: "▤" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside style={{
      width: 220,
      minWidth: 220,
      background: "var(--bg-secondary)",
      borderRight: "1px solid var(--border)",
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      position: "fixed",
      left: 0,
      top: 0,
      zIndex: 50,
    }}>
      {/* Logo */}
      <div style={{
        padding: "20px 20px 16px",
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 34,
            height: 34,
            borderRadius: 8,
            background: "linear-gradient(135deg, #d4a843 0%, #f5c842 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 16,
            fontWeight: 900,
            color: "#000",
            flexShrink: 0,
          }}>
            AU
          </div>
          <div>
            <p style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1.2 }}>XAUUSD</p>
            <p style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" }}>AI Control Center</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "12px 10px", overflowY: "auto" }}>
        <p style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)", padding: "4px 10px 8px" }}>
          Navigation
        </p>
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "9px 10px",
                borderRadius: 8,
                marginBottom: 2,
                textDecoration: "none",
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
                background: active ? "rgba(59,130,246,0.12)" : "transparent",
                borderLeft: active ? "2px solid var(--accent-blue)" : "2px solid transparent",
                transition: "all 0.15s",
              }}
            >
              <span style={{ fontSize: 16, width: 20, textAlign: "center", flexShrink: 0 }}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
        <p style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.05em" }}>FTMO PHASE 2 · v16</p>
        <p style={{ fontSize: 10, color: "var(--text-muted)" }}>€160,000 Capital</p>
      </div>
    </aside>
  );
}
