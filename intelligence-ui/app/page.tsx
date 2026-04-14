'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Brain,
  CalendarDays,
  Clock3,
  Flame,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  TriangleAlert,
} from 'lucide-react';
import {
  Bar,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type AnalyticsPayload = {
  today_snapshot: {
    total_deep_minutes: number;
    best_focus_hour: string | null;
    current_streak: number;
  };
  today_analysis: {
    productive_minutes: number;
    neutral_minutes: number;
    waste_minutes: number;
    avg_focus_score: number | null;
    top_waste_activity: string | null;
  };
  week_analysis: {
    total_minutes: number;
    productive_share_pct: number;
    waste_share_pct: number;
    top_productive_activity: string | null;
    top_waste_activity: string | null;
  };
  weekly_trend: { date: string; avg_focus: number | null; total_minutes: number }[];
  focus_heatmap: {
    start_date: string;
    values: (number | null)[][];
  };
  category_breakdown: { name: string; minutes: number }[];
  detailed_activity: {
    label: string;
    app: string;
    classification: 'Productive' | 'Neutral' | 'Waste';
    minutes: number;
    sessions: number;
    last_seen: string;
  }[];
  assistant_insights: string[];
  assistant_insights_source: string;
};

type RankedSchedulePayload = {
  ranked_blocks: {
    start_time: string;
    end_time: string;
    tradeoff_score: number;
    confidence: number;
    suggested_task: string;
  }[];
};

type PrivacyStatusPayload = {
  local_only_training: boolean;
  note: string;
};

type RegimePayload = { regime_label: string; regime_score: number };
type QualityPayload = { proxy_accuracy?: number; avg_confidence?: number; fallback_rate?: number };
type DecisionRecommendPayload = { recommended_actions: { action: string; predicted_uplift_pct: number }[] };
type InfluenceGraphPayload = {
  graph: { leverage_recommendations: { anchor_activity: string; recommendation: string }[] };
};

const STATUS_COLORS: Record<'Productive' | 'Neutral' | 'Waste', string> = {
  Productive: 'text-emerald-700 bg-emerald-100 border-emerald-200',
  Neutral: 'text-sky-700 bg-sky-100 border-sky-200',
  Waste: 'text-rose-700 bg-rose-100 border-rose-200',
};

function panelClass(extra = '') {
  return `rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${extra}`;
}

function formatHourLabel(iso: string | null) {
  if (!iso) return '--';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatTimeRange(start: string, end: string) {
  const s = new Date(start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const e = new Date(end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `${s} - ${e}`;
}

function heatColor(value: number | null) {
  if (value === null) return 'bg-slate-100';
  if (value >= 8) return 'bg-emerald-500';
  if (value >= 6) return 'bg-emerald-400';
  if (value >= 4) return 'bg-sky-400';
  if (value >= 2) return 'bg-amber-300';
  return 'bg-rose-300';
}

export default function ZenithIntelligencePage() {
  const [analytics, setAnalytics] = useState<AnalyticsPayload | null>(null);
  const [schedule, setSchedule] = useState<RankedSchedulePayload | null>(null);
  const [privacy, setPrivacy] = useState<PrivacyStatusPayload | null>(null);
  const [regime, setRegime] = useState<RegimePayload | null>(null);
  const [quality, setQuality] = useState<QualityPayload | null>(null);
  const [decision, setDecision] = useState<DecisionRecommendPayload | null>(null);
  const [graph, setGraph] = useState<InfluenceGraphPayload | null>(null);
  const [manualLog, setManualLog] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const fetchJson = async <T,>(url: string): Promise<T | null> => {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return (await res.json()) as T;
      } catch {
        return null;
      }
    };

    const load = async () => {
      setLoading(true);
      const [analyticsRes, scheduleRes, privacyRes, regimeRes, qualityRes, decisionRes, graphRes] = await Promise.all([
        fetchJson<AnalyticsPayload>('http://127.0.0.1:8000/api/analytics/'),
        fetchJson<RankedSchedulePayload>('http://127.0.0.1:8000/api/schedule/ranked/'),
        fetchJson<PrivacyStatusPayload>('http://127.0.0.1:8000/api/privacy/status/'),
        fetchJson<RegimePayload>('http://127.0.0.1:8000/api/analytics/regime/'),
        fetchJson<QualityPayload>('http://127.0.0.1:8000/api/analytics/classification-quality/'),
        fetchJson<DecisionRecommendPayload>('http://127.0.0.1:8000/api/decision/recommend/'),
        fetchJson<InfluenceGraphPayload>('http://127.0.0.1:8000/api/graph/influence/?rebuild=0'),
      ]);
      setAnalytics(analyticsRes);
      setSchedule(scheduleRes);
      setPrivacy(privacyRes);
      setRegime(regimeRes);
      setQuality(qualityRes);
      setDecision(decisionRes);
      setGraph(graphRes);
      setLoading(false);
    };

    void load();
  }, []);

  const totalFocusBlocks = useMemo(() => {
    if (!analytics?.focus_heatmap?.values) return 0;
    let count = 0;
    for (const row of analytics.focus_heatmap.values) {
      for (const cell of row) {
        if (cell !== null) count += 1;
      }
    }
    return count;
  }, [analytics]);

  const submitManualLog = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!manualLog.trim()) return;
    setSubmitting(true);
    try {
      await fetch('http://127.0.0.1:8000/ingest/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: 'Manual Entry',
          duration_minutes: 30,
          metadata: { raw_text: manualLog },
        }),
      });
      setManualLog('');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-50 text-slate-900">
        <div className="mx-auto max-w-7xl px-6 py-12">Loading Zenith Intelligence...</div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <header className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-slate-900 p-3 text-white">
              <Brain className="h-6 w-6" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Personal Analytics Command Center</p>
              <h1 className="text-3xl font-semibold tracking-tight">Zenith Intelligence</h1>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              {privacy?.local_only_training ? 'Local-only mode' : 'Cloud assisted mode'}
            </span>
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-600">
              <Sparkles className="h-4 w-4 text-violet-600" />
              Regime: {regime?.regime_label ?? 'unknown'}
            </span>
          </div>
        </header>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Deep Work</p>
            <p className="mt-2 text-2xl font-semibold text-emerald-700">{analytics?.today_analysis.productive_minutes ?? 0}m</p>
          </div>
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Waste</p>
            <p className="mt-2 text-2xl font-semibold text-rose-700">{analytics?.today_analysis.waste_minutes ?? 0}m</p>
          </div>
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Neutral</p>
            <p className="mt-2 text-2xl font-semibold text-sky-700">{analytics?.today_analysis.neutral_minutes ?? 0}m</p>
          </div>
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Avg Focus</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{analytics?.today_analysis.avg_focus_score ?? '--'}</p>
          </div>
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Best Hour</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{formatHourLabel(analytics?.today_snapshot.best_focus_hour ?? null)}</p>
          </div>
          <div className={panelClass()}>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Streak</p>
            <p className="mt-2 text-2xl font-semibold text-amber-700">{analytics?.today_snapshot.current_streak ?? 0} days</p>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-12">
          <div className="space-y-6 lg:col-span-8">
            <div className={panelClass()}>
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold">Weekly Trend</h2>
                <span className="text-sm text-slate-500">Focus score + total minutes</span>
              </div>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={analytics?.weekly_trend ?? []}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 12 }} />
                    <YAxis yAxisId="left" tick={{ fill: '#64748b', fontSize: 12 }} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fill: '#64748b', fontSize: 12 }} />
                    <Tooltip />
                    <Legend />
                    <Bar yAxisId="right" dataKey="total_minutes" fill="#cbd5e1" name="Minutes" radius={[6, 6, 0, 0]} />
                    <Line yAxisId="left" type="monotone" dataKey="avg_focus" stroke="#0f766e" strokeWidth={2.5} dot={{ r: 3 }} name="Avg Focus" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className={panelClass()}>
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold">Focus Heatmap</h2>
                <span className="text-sm text-slate-500">Last 7 days x 24 hours</span>
              </div>
              <div className="overflow-x-auto">
                <div className="min-w-[720px] space-y-2">
                  {(analytics?.focus_heatmap.values ?? []).map((row, rowIdx) => (
                    <div key={rowIdx} className="grid grid-cols-24 gap-1">
                      {row.map((cell, colIdx) => (
                        <div
                          key={`${rowIdx}-${colIdx}`}
                          className={`h-4 rounded ${heatColor(cell)}`}
                          title={`Day ${rowIdx + 1}, hour ${colIdx}: ${cell ?? 'no data'}`}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
              <p className="mt-3 text-sm text-slate-500">Populated focus cells: {totalFocusBlocks}</p>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Detailed Activity Log</h2>
              <div className="max-h-80 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white">
                    <tr className="text-left text-slate-500">
                      <th className="py-2">Activity</th>
                      <th className="py-2">Type</th>
                      <th className="py-2 text-right">Sessions</th>
                      <th className="py-2 text-right">Minutes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(analytics?.detailed_activity ?? []).map((item, idx) => (
                      <tr key={`${item.label}-${idx}`} className="border-t border-slate-100">
                        <td className="py-2">
                          <p className="font-medium text-slate-900">{item.label}</p>
                          <p className="text-xs text-slate-500">{item.app}</p>
                        </td>
                        <td className="py-2">
                          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[item.classification]}`}>
                            {item.classification}
                          </span>
                        </td>
                        <td className="py-2 text-right">{item.sessions}</td>
                        <td className="py-2 text-right font-medium">{item.minutes}m</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <aside className="space-y-6 lg:col-span-4">
            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Category Breakdown</h2>
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={analytics?.category_breakdown ?? []} dataKey="minutes" nameKey="name" innerRadius={50} outerRadius={88}>
                      {(analytics?.category_breakdown ?? []).map((entry, index) => {
                        const normalized = entry.name.toLowerCase();
                        const fill = normalized.includes('waste')
                          ? '#fb7185'
                          : normalized.includes('productive')
                            ? '#10b981'
                            : '#38bdf8';
                        return <Cell key={index} fill={fill} />;
                      })}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Assistant Insights</h2>
              <ul className="space-y-3 text-sm text-slate-700">
                {(analytics?.assistant_insights ?? ['Not enough data yet.']).map((insight, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <TrendingUp className="mt-0.5 h-4 w-4 text-slate-400" />
                    <span>{insight}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs text-slate-500">Source: {analytics?.assistant_insights_source ?? 'rule-based fallback'}</p>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Model Diagnostics</h2>
              <div className="space-y-3 text-sm text-slate-700">
                <p>Classifier accuracy: {((quality?.proxy_accuracy ?? 0) * 100).toFixed(1)}%</p>
                <p>Avg confidence: {((quality?.avg_confidence ?? 0) * 100).toFixed(1)}%</p>
                <p>Fallback rate: {((quality?.fallback_rate ?? 0) * 100).toFixed(1)}%</p>
                <p>Regime score: {((regime?.regime_score ?? 0) * 100).toFixed(0)}%</p>
              </div>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Recommended Blocks</h2>
              <div className="space-y-2">
                {(schedule?.ranked_blocks ?? []).slice(0, 3).map((block, idx) => (
                  <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{formatTimeRange(block.start_time, block.end_time)}</p>
                    <p className="mt-1 font-medium text-slate-900">{block.suggested_task}</p>
                    <p className="mt-1 text-xs text-slate-500">Confidence {(block.confidence * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Interventions</h2>
              <div className="space-y-2 text-sm text-slate-700">
                {(decision?.recommended_actions ?? []).slice(0, 3).map((rec, idx) => (
                  <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p className="font-medium capitalize">{rec.action.replace(/_/g, ' ')}</p>
                    <p className="text-xs text-slate-500">Expected uplift: +{rec.predicted_uplift_pct}%</p>
                  </div>
                ))}
              </div>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-4 text-lg font-semibold">Habit Influence</h2>
              <div className="space-y-2 text-sm text-slate-700">
                {(graph?.graph.leverage_recommendations ?? []).slice(0, 3).map((row, idx) => (
                  <div key={idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p className="font-medium">{row.anchor_activity}</p>
                    <p className="text-xs text-slate-500">{row.recommendation}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className={panelClass()}>
              <h2 className="mb-3 text-lg font-semibold">Manual Context Log</h2>
              <p className="mb-3 text-sm text-slate-600">Add notes to improve assistant recommendations.</p>
              <form className="space-y-3" onSubmit={submitManualLog}>
                <input
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-500"
                  placeholder="Example: YouTube DSA lecture, focus 7"
                  value={manualLog}
                  onChange={(e) => setManualLog(e.target.value)}
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700 disabled:opacity-60"
                >
                  {submitting ? 'Saving...' : 'Save to Zenith Intelligence'}
                </button>
              </form>
            </div>

            <div className={panelClass('border-amber-200 bg-amber-50')}>
              <p className="flex items-start gap-2 text-sm text-amber-900">
                <TriangleAlert className="mt-0.5 h-4 w-4" />
                Productive is green, waste is red, and neutral is blue in the activity log.
              </p>
            </div>
          </aside>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <div className={panelClass()}>
            <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-500">
              <Target className="h-4 w-4" /> Top Productive Driver
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{analytics?.week_analysis.top_productive_activity ?? 'No data'}</p>
          </div>
          <div className={panelClass()}>
            <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-500">
              <TriangleAlert className="h-4 w-4" /> Top Distraction Driver
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{analytics?.week_analysis.top_waste_activity ?? 'No data'}</p>
          </div>
          <div className={panelClass()}>
            <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-500">
              <CalendarDays className="h-4 w-4" /> Weekly Minutes
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-900">{analytics?.week_analysis.total_minutes ?? 0} minutes tracked</p>
          </div>
        </section>

        <section className={panelClass('flex flex-wrap items-center gap-4')}>
          <span className="inline-flex items-center gap-2 rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800">
            <Flame className="h-3.5 w-3.5" /> Productive
          </span>
          <span className="inline-flex items-center gap-2 rounded-full bg-rose-100 px-3 py-1 text-xs font-medium text-rose-800">
            <TriangleAlert className="h-3.5 w-3.5" /> Waste
          </span>
          <span className="inline-flex items-center gap-2 rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-800">
            <Clock3 className="h-3.5 w-3.5" /> Neutral
          </span>
        </section>
      </div>
    </main>
  );
}
