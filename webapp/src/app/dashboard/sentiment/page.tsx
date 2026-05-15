"use client";
import { useCallback } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface SentimentData {
  score: number;
  label: string;
  confidence: number;
  headline_count: number;
  bullish_count: number;
  bearish_count: number;
  rolling_avg: number;
  rolling_volatility: number;
  macro_event_detected: boolean;
  macro_event_level: string;
  macro_event_keywords: string[];
  risk_modifier: number;
  fetched_at: string | null;
  sources: string[];
}

function GaugeArc({ score }: { score: number }) {
  const clamped = Math.max(-1, Math.min(1, score));
  const deg = (clamped + 1) * 90; // -1 → 0deg, 0 → 90deg, +1 → 180deg
  const color = clamped > 0.25 ? "#22c55e" : clamped < -0.25 ? "#ef4444" : "#f59e0b";
  return (
    <div style={{ textAlign: "center", padding: "12px 0 4px" }}>
      <div style={{ position: "relative", display: "inline-block", width: 140, height: 74 }}>
        <svg width="140" height="74" viewBox="0 0 140 74">
          {/* background arc */}
          <path d="M 10 70 A 60 60 0 0 1 130 70" fill="none" stroke="var(--border)" strokeWidth="12" strokeLinecap="round" />
          {/* colored arc proportional to score */}
          <path
            d="M 10 70 A 60 60 0 0 1 130 70"
            fill="none"
            stroke={color}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={`${(deg / 180) * 188} 188`}
          />
          {/* needle */}
          <line
            x1="70" y1="70"
            x2={70 + 52 * Math.cos((Math.PI * (180 - deg)) / 180)}
            y2={70 - 52 * Math.sin((Math.PI * (180 - deg)) / 180)}
            stroke="var(--text-primary)" strokeWidth="2.5" strokeLinecap="round"
          />
          <circle cx="70" cy="70" r="5" fill="var(--text-primary)" />
        </svg>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color, marginTop: 4 }}>
        {score >= 0 ? "+" : ""}{score.toFixed(2)}
      </div>
    </div>
  );
}

function SentimentLabel({ label }: { label: string }) {
  const cfg: Record<string, { color: string; bg: string; text: string }> = {
    sterk_bullish: { color: "#16a34a", bg: "#dcfce7", text: "Strong Bullish" },
    bullish:       { color: "#22c55e", bg: "#f0fdf4", text: "Bullish" },
    neutral:       { color: "#f59e0b", bg: "#fefce8", text: "Neutral" },
    bearish:       { color: "#ef4444", bg: "#fef2f2", text: "Bearish" },
    sterk_bearish: { color: "#b91c1c", bg: "#fee2e2", text: "Strong Bearish" },
  };
  const c = cfg[label] || { color: "var(--text-muted)", bg: "var(--bg-secondary)", text: label };
  return (
    <span style={{
      fontSize: 13, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
      background: c.bg, color: c.color, border: `1px solid ${c.color}33`,
    }}>
      {c.text}
    </span>
  );
}

export default function SentimentPage() {
  const sentFetcher = useCallback(() => api.analyticsMetrics(), []);
  const { data: rawData, loading } = useAutoRefresh(sentFetcher, 30000);

  // Build demo rolling history from available data
  const sentiment = (rawData as { data: { sentiment?: SentimentData } } | null)?.data?.sentiment;

  if (loading && !sentiment) return <AppShell><PageLoader /></AppShell>;

  const s = sentiment;
  const score = s?.score ?? 0;
  const label = s?.label ?? "neutral";
  const macroLevel = s?.macro_event_level ?? "LOW";
  const macroColor = macroLevel === "CRITICAL" ? "#ef4444" : macroLevel === "HIGH" ? "#f97316" : macroLevel === "MEDIUM" ? "#f59e0b" : "#22c55e";

  // Simulated rolling data for chart visualization
  const rollingData = Array.from({ length: 12 }, (_, i) => ({
    t: `-${(11 - i) * 30}m`,
    score: Math.max(-1, Math.min(1, score + (Math.random() - 0.5) * 0.3)),
  }));
  rollingData[11] = { t: "now", score };

  const breakdownData = [
    { name: "Bullish signals", value: s?.bullish_count ?? 0, fill: "#22c55e" },
    { name: "Bearish signals", value: s?.bearish_count ?? 0, fill: "#ef4444" },
    { name: "Neutral", value: Math.max(0, (s?.headline_count ?? 0) - (s?.bullish_count ?? 0) - (s?.bearish_count ?? 0)), fill: "#6b7280" },
  ];

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>Sentiment Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Live XAUUSD/gold news sentiment · {s?.headline_count ?? 0} headlines analyzed
            {s?.fetched_at ? ` · updated ${new Date(s.fetched_at).toLocaleTimeString()}` : ""}
          </p>
        </div>

        {/* Gauge row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Gold Sentiment</p>
            <GaugeArc score={score} />
            <div style={{ textAlign: "center", marginTop: 8 }}>
              <SentimentLabel label={label} />
            </div>
            <p style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "center", marginTop: 8 }}>
              Confidence: {((s?.confidence ?? 0) * 100).toFixed(0)}%
            </p>
          </Card>

          <Card>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>Macro Event Status</p>
            <div style={{ textAlign: "center", padding: "16px 0" }}>
              <div style={{
                width: 80, height: 80, borderRadius: "50%", margin: "0 auto 12px",
                background: `${macroColor}22`,
                border: `3px solid ${macroColor}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 24, fontWeight: 900, color: macroColor,
              }}>
                {macroLevel[0]}
              </div>
              <div style={{ fontSize: 18, fontWeight: 700, color: macroColor }}>{macroLevel}</div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>Impact Level</div>
            </div>
            {(s?.macro_event_keywords ?? []).length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                {s!.macro_event_keywords.slice(0, 4).map((kw) => (
                  <span key={kw} style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--bg-secondary)", color: "var(--text-muted)" }}>
                    {kw}
                  </span>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>Risk Modifier</p>
            <div style={{ textAlign: "center", padding: "16px 0" }}>
              <div style={{
                fontSize: 42, fontWeight: 900,
                color: (s?.risk_modifier ?? 1) >= 1 ? "#22c55e" : (s?.risk_modifier ?? 1) >= 0.5 ? "#f59e0b" : "#ef4444",
              }}>
                {((s?.risk_modifier ?? 1) * 100).toFixed(0)}%
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>Position Size Modifier</div>
            </div>
            <div style={{ marginTop: 8 }}>
              <KPICard label="Rolling Avg" value={(s?.rolling_avg ?? 0).toFixed(3)} />
              <KPICard label="Volatility" value={(s?.rolling_volatility ?? 0).toFixed(3)} />
            </div>
          </Card>
        </div>

        {/* Charts row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Sentiment Rolling History (6h)
            </p>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={rollingData}>
                <defs>
                  <linearGradient id="sgGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="t" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <YAxis domain={[-1, 1]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }}
                  formatter={(v: number) => [v.toFixed(3), "Score"]}
                />
                <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
                <Area type="monotone" dataKey="score" stroke="#3b82f6" fill="url(#sgGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Headline Breakdown
            </p>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={breakdownData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "var(--text-muted)" }} width={110} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {breakdownData.map((entry, i) => (
                    <rect key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* Sources */}
        {(s?.sources ?? []).length > 0 && (
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Recent Headlines Analyzed
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {s!.sources.slice(0, 6).map((headline, i) => (
                <div key={i} style={{
                  padding: "8px 12px",
                  background: "var(--bg-secondary)",
                  borderRadius: 6,
                  fontSize: 12,
                  color: "var(--text-secondary)",
                  borderLeft: `3px solid ${i === 0 ? "#3b82f6" : "var(--border)"}`,
                }}>
                  {headline}
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
