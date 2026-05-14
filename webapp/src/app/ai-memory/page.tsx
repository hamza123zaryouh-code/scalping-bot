"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from "recharts";
import type { ModelSnapshot, StrategyVersion } from "../../lib/types";

export default function AIMemoryPage() {
  const patternsFetcher = useCallback(() => api.patterns(), []);
  const trainingFetcher = useCallback(() => api.trainingData(), []);
  const modelFetcher = useCallback(() => api.modelHistory(), []);
  const evolutionFetcher = useCallback(() => api.strategyEvolution(), []);
  const runtimeFetcher = useCallback(() => api.runtimeState(), []);

  const { data: patternsRes } = useAutoRefresh(patternsFetcher, 30000);
  const { data: trainingRes, loading: trainLoading } = useAutoRefresh(trainingFetcher, 30000);
  const { data: modelRes } = useAutoRefresh(modelFetcher, 30000);
  const { data: evolutionRes } = useAutoRefresh(evolutionFetcher, 60000);
  const { data: runtimeRes } = useAutoRefresh(runtimeFetcher, 15000);

  const patterns = (patternsRes as { data: { winning_patterns: unknown; losing_patterns: unknown; best_parameters: unknown } } | null)?.data;
  const training = (trainingRes as { data: { records: number; wins: number; losses: number; win_rate: number; features: string[] } } | null)?.data;
  const models = (modelRes as { data: { snapshots: ModelSnapshot[]; total: number } } | null)?.data?.snapshots ?? [];
  const evolution = (evolutionRes as { data: { versions: StrategyVersion[]; total: number; latest: string; notes: string } } | null)?.data;
  const runtime = (runtimeRes as { data: Record<string, unknown> } | null)?.data;

  const modelChartData = models.slice(-10).map((m) => ({
    date: new Date(m.trained_at).toLocaleDateString(),
    accuracy: parseFloat((m.accuracy * 100).toFixed(1)),
    f1: parseFloat((m.f1_score * 100).toFixed(1)),
  }));

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Training Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {[
            { label: "Training Records", value: training?.records ?? 0, color: "var(--accent-blue)" },
            { label: "Win Samples", value: training?.wins ?? 0, color: "var(--accent-green)" },
            { label: "Loss Samples", value: training?.losses ?? 0, color: "var(--accent-red)" },
            { label: "Sample Win Rate", value: `${training?.win_rate ?? 0}%`, color: "var(--accent-yellow)" },
          ].map((s) => (
            <div key={s.label} className="card">
              <p className="stat-label">{s.label}</p>
              <p style={{ fontSize: 26, fontWeight: 700, color: s.color, marginTop: 6 }}>{s.value}</p>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Strategy Evolution */}
          <Card title="Strategy Evolution" subtitle={`${evolution?.total ?? 0} versions · Latest: v${evolution?.latest ?? "?"}`}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
              {(evolution?.versions ?? []).slice().reverse().map((v, i) => (
                <div key={i} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "8px 12px",
                  background: i === 0 ? "rgba(59,130,246,0.08)" : "var(--bg-secondary)",
                  borderRadius: 8,
                  border: `1px solid ${i === 0 ? "rgba(59,130,246,0.2)" : "var(--border-subtle)"}`,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {i === 0 && <Badge variant="blue">LATEST</Badge>}
                    <span style={{ fontSize: 13, fontWeight: i === 0 ? 600 : 400, color: i === 0 ? "var(--text-primary)" : "var(--text-secondary)" }}>
                      {v.file}
                    </span>
                  </div>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {new Date(v.modified).toLocaleDateString()} · {(v.size_bytes / 1024).toFixed(0)}KB
                  </span>
                </div>
              ))}
              {!evolution?.versions?.length && (
                <p style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: "30px 0" }}>No strategy files found</p>
              )}
            </div>
          </Card>

          {/* ML Model History */}
          <Card title="ML Model History" subtitle={`${models.length} trained snapshots`}>
            {models.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={modelChartData} margin={{ top: 0, right: 4, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 9, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 11 }} />
                    <Bar dataKey="accuracy" fill="#3b82f6" radius={[3, 3, 0, 0]} name="Accuracy %" maxBarSize={20} />
                    <Bar dataKey="f1" fill="#10b981" radius={[3, 3, 0, 0]} name="F1 %" maxBarSize={20} />
                  </BarChart>
                </ResponsiveContainer>
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
                  {models.slice(-3).reverse().map((m, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                      <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>{new Date(m.trained_at).toLocaleString()}</span>
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        Acc: {(m.accuracy * 100).toFixed(1)}% · F1: {(m.f1_score * 100).toFixed(1)}% · n={m.sample_count}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: "40px 0" }}>
                No ML model snapshots yet
              </p>
            )}
          </Card>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {/* Winning Patterns */}
          <Card title="Winning Patterns" glow="green">
            <pre style={{
              fontSize: 11,
              color: "var(--accent-green)",
              background: "rgba(16,185,129,0.04)",
              borderRadius: 8,
              padding: 12,
              overflow: "auto",
              maxHeight: 240,
              fontFamily: "monospace",
              lineHeight: 1.6,
            }}>
              {patterns?.winning_patterns
                ? JSON.stringify(patterns.winning_patterns, null, 2).slice(0, 1200)
                : "No winning patterns stored yet.\nPatterns are built from closed trade data."}
            </pre>
          </Card>

          {/* Losing Patterns */}
          <Card title="Losing Patterns" glow="red">
            <pre style={{
              fontSize: 11,
              color: "var(--accent-red)",
              background: "rgba(239,68,68,0.04)",
              borderRadius: 8,
              padding: 12,
              overflow: "auto",
              maxHeight: 240,
              fontFamily: "monospace",
              lineHeight: 1.6,
            }}>
              {patterns?.losing_patterns
                ? JSON.stringify(patterns.losing_patterns, null, 2).slice(0, 1200)
                : "No losing patterns stored yet.\nPatterns are extracted from failed trades."}
            </pre>
          </Card>

          {/* Runtime State */}
          <Card title="Runtime AI State">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {runtime && Object.entries(runtime).map(([k, v]) => (
                <div key={k} style={{ padding: "8px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                  <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 4 }}>{k}</p>
                  <pre style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                    {v && typeof v === "object" ? JSON.stringify(v, null, 1).slice(0, 200) : String(v ?? "—")}
                  </pre>
                </div>
              ))}
              {!runtime && (
                <p style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", padding: "20px 0" }}>Loading…</p>
              )}
            </div>
          </Card>
        </div>

        {/* Feature Importance */}
        {models.length > 0 && models[models.length - 1].feature_importances && (
          <Card title="Feature Importances" subtitle="Latest ML model">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
              {Object.entries(models[models.length - 1].feature_importances)
                .sort(([, a], [, b]) => (b as number) - (a as number))
                .slice(0, 12)
                .map(([feat, imp]) => (
                  <div key={feat} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 11, color: "var(--text-secondary)", width: 120, flexShrink: 0 }}>{feat}</span>
                    <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{
                        width: `${Math.round((imp as number) * 100)}%`,
                        height: "100%",
                        background: "var(--accent-blue)",
                        borderRadius: 3,
                      }} />
                    </div>
                    <span style={{ fontSize: 10, color: "var(--text-muted)", width: 32, textAlign: "right" }}>
                      {((imp as number) * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
