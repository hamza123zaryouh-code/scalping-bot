"use client";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

interface AppShellProps {
  children: React.ReactNode;
  mode?: string;
  lastUpdate?: string;
}

export function AppShell({ children, mode, lastUpdate }: AppShellProps) {
  return (
    <div className="app-shell" style={{ display: "flex", minHeight: "100vh", background: "var(--bg-primary)" }}>
      <Sidebar />
      <div
        className="app-shell-content"
        style={{ flex: 1, marginLeft: 220, display: "flex", flexDirection: "column", minHeight: "100vh" }}
      >
        <TopBar mode={mode} lastUpdate={lastUpdate} />
        <main style={{ flex: 1, padding: "24px", overflow: "auto" }}>
          {children}
        </main>
      </div>
    </div>
  );
}
