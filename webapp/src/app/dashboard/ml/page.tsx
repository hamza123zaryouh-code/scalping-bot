"use client";
import { useCallback } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import type { ModelSnapshot } from "../../../lib/types";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";

interface MLMetrics {
  model_snapshots: ModelSnapshot[];
  feature_importance: Record<string, number>;
  latest_accuracy: number;
  latest_f1: number;
  sample_count: number;
  last_trained_at: string | null;
}

const FEATURE_COLORS = [
  "#3b82f6", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#ec4899", "#84cc16", "#f97316", "#6366f1",
];

export default function MLDashboardPage() {
  const mlFetcher = useCallback(() => api.analyticsML(), []);
  const { data: raw, loading } = useAutoRefresh(mlFetcher, 60000);

  if (loading) return <AppShell><PageLoader /></AppShell>;

  const snapshots: ModelSnapshot[] = (raw as { data: ModelSnapshot[] } | null)?.data ?? [];
  const latest = snapshots[snapshots.length - 1];

  const accuracyHistory = snapshots.map((s, i) => ({
    n: i + 1,
    accuracy: parseFloat((s.accuracy * 100).toFixed(1)),
    f1: parseFloat((s.f1_score * 100).toFixed(1)),
    samples: s.sample_count,
    date: s.trained_at ? new Date(s.trained_at).toLocaleDateString() : `#${i + 1}`,
  }));

  const featureImportance = Object.entries(latest?.feature_importance ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 12)
    .map(([name, val]) => ({ name: name.replace(/_/g, " "), val: parseFloat((val * 100).toFixed(1)) }));

  const sampleDistribution = snapshots.map((s, i) => ({
    date: s.trained_at ? new Date(s.trained_at).toLocaleDateString() : `v${i + 1}`,
    samples: s.sample_count,
    accuracy: parseFloat((s.accuracy * 100).toFixed(1)),
  }));

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>ML Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            GradientBoosting model performance · {snapshots.length} training runs
            {latest?.trained_at ? ` · last trained ${new Date(latest.trained_at).toLocaleString()}` : ""}
          </p>
        </div>

        {/* KPI row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <Card>
            <KPICard
              label="Latest Accuracy"
              value={latest ? `${(latest.accuracy * 100).toFixed(1)}%` : "—"}
              trend={latest && latest.accuracy > 0.6 ? "up" : "neutral"}
            />
          </Card>
          <Card>
            <KPICard
              label="F1 Score"
              value={latest ? `${(latest.f1_score * 100).toFixed(1)}%` : "—"}
            />
          </Card>
          <Card>
            <KPICard
              label="Training Samples"
              value={latest?.sample_count?.toString() ?? "0"}
            />
          </Card>
          <Card>
            <KPICard
              label="Training Runs"
              value={snapshots.length.toString()}
            />
          </Card>
        </div>

        {/* Charts row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Accuracy & F1 History
            </p>
            {accuracyHistory.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                No training history yet. System needs ≥20 closed trades to train.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={accuracyHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <YAxis domain={[40, 100]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }}
                    formatter={(v: number) => [`${v}%`]}
                  />
                  <Line type="monotone" dataKey="accuracy" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} name="Accuracy" />
                  <Line type="monotone" dataKey="f1" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3 }} name="F1 Score" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Feature Importance
            </p>
            {featureImportance.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                Feature data available after first training run.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={featureImportance} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: "var(--text-muted)" }} width={120} />
                  <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                  <Bar dataKey="val" radius={[0, 4, 4, 0]}>
                    {featureImportance.map((_, i) => (
                      <Cell key={i} fill={FEATURE_COLORS[i % FEATURE_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </div>

        {/* Sample growth */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            Training Sample Growth
          </p>
          {sampleDistribution.length === 0 ? (
            <div style={{ textAlign: "center", padding: "30px 0", color: "var(--text-muted)", fontSize: 13 }}>
              No training data available yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={sampleDistribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                <Bar dataKey="samples" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Samples" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Model history table */}
        {snapshots.length > 0 && (
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Model Training History
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
                    {["Version", "Date", "Accuracy", "F1 Score", "Samples", "Overrides"].map((h) => (
                      <th key={h} style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...snapshots].reverse().slice(0, 10).map((s, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>v{snapshots.length - i}</td>
                      <td style={{ padding: "8px 10px" }}>{s.trained_at ? new Date(s.trained_at).toLocaleString() : "—"}</td>
                      <td style={{ padding: "8px 10px" }}>
                        <Badge variant={s.accuracy > 0.6 ? "success" : "warning"}>
                          {(s.accuracy * 100).toFixed(1)}%
                        </Badge>
                      </td>
                      <td style={{ padding: "8px 10px" }}>{(s.f1_score * 100).toFixed(1)}%</td>
                      <td style={{ padding: "8px 10px" }}>{s.sample_count}</td>
                      <td style={{ padding: "8px 10px", color: "var(--text-muted)", fontSize: 11 }}>
                        {s.parameter_overrides ? Object.keys(s.parameter_overrides).join(", ") || "none" : "none"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
