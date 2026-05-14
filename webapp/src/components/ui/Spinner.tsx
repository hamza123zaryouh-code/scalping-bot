export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ animation: "spin 0.8s linear infinite" }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="10" stroke="#1e2d40" strokeWidth="3" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="#3b82f6" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function PageLoader() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", minHeight: 200 }}>
      <Spinner size={32} />
    </div>
  );
}
