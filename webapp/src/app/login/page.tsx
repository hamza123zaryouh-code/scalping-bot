"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.login(username, password);
      setToken(res.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg-primary)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      <div style={{ width: "100%", maxWidth: 380, padding: 24 }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{
            width: 56,
            height: 56,
            borderRadius: 14,
            background: "linear-gradient(135deg, #d4a843 0%, #f5c842 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 22,
            fontWeight: 900,
            color: "#000",
            margin: "0 auto 16px",
          }}>
            AU
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)", marginBottom: 4 }}>
            XAUUSD Control Center
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            AI Trading Management Dashboard
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--text-muted)", marginBottom: 6 }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              style={{ width: "100%", fontSize: 14 }}
              required
              autoComplete="username"
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--text-muted)", marginBottom: 6 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{ width: "100%", fontSize: 14 }}
              required
              autoComplete="current-password"
            />
          </div>

          {error && (
            <div style={{
              background: "rgba(239,68,68,0.08)",
              border: "1px solid rgba(239,68,68,0.2)",
              borderRadius: 8,
              padding: "10px 14px",
              fontSize: 13,
              color: "#f87171",
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              background: loading ? "rgba(59,130,246,0.4)" : "var(--accent-blue)",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "11px 20px",
              fontSize: 14,
              fontWeight: 600,
              width: "100%",
              marginTop: 4,
              transition: "background 0.2s",
            }}
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <p style={{ textAlign: "center", fontSize: 11, color: "var(--text-muted)", marginTop: 24 }}>
          FTMO Compliant · XAUUSD Strategy v16
        </p>
      </div>
    </div>
  );
}
