interface AlertProps {
  type?: "error" | "warning" | "info" | "success";
  title?: string;
  children: React.ReactNode;
}

const ALERT_STYLES = {
  error: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)", color: "#f87171" },
  warning: { bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.2)", color: "#fbbf24" },
  info: { bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.2)", color: "#60a5fa" },
  success: { bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.2)", color: "#34d399" },
};

const ICONS = { error: "✕", warning: "⚠", info: "ℹ", success: "✓" };

export function Alert({ type = "info", title, children }: AlertProps) {
  const s = ALERT_STYLES[type];
  return (
    <div style={{
      background: s.bg,
      border: `1px solid ${s.border}`,
      borderRadius: 8,
      padding: "12px 16px",
      display: "flex",
      gap: 10,
      alignItems: "flex-start",
    }}>
      <span style={{ color: s.color, fontWeight: 700, fontSize: 14, lineHeight: 1.4 }}>{ICONS[type]}</span>
      <div>
        {title && <p style={{ color: s.color, fontWeight: 600, fontSize: 13, marginBottom: 2 }}>{title}</p>}
        <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>{children}</p>
      </div>
    </div>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return <Alert type="error" title="Error">{message}</Alert>;
}
