'use client';

import { useEffect, useMemo, useState, ReactNode } from 'react';
import { 
  Zap, 
  Target, 
  Activity, 
  Lock, 
  ShieldCheck, 
  Cpu, 
  TrendingUp, 
  Clock, 
  Search,
  CheckCircle2,
  AlertCircle,
  Command
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Area,
  AreaChart
} from 'recharts';

// --- Types ---
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
  weekly_trend: {
    date: string;
    avg_focus: number | null;
    total_minutes: number;
  }[];
  focus_heatmap: {
    start_date: string;
    values: (number | null)[][];
  };
  classification_totals: {
    Productive: number;
    Neutral: number;
    Waste: number;
  };
  detailed_activity: {
    label: string;
    app: string;
    classification: 'Productive' | 'Neutral' | 'Waste';
    minutes: number;
    sessions: number;
    last_seen: string;
  }[];
  category_breakdown: {
    name: string;
    minutes: number;
  }[];
  assistant_insights: string[];
  assistant_insights_source: string;
  ml_phase1: {
    feature_store: {
      lookback_days: number;
      row_count: number;
      columns: string[];
    };
    probabilistic_forecast: {
      timestamp: string;
      hour: number;
      p10: number;
      p50: number;
      p90: number;
      confidence: number;
    }[];
    anomaly_detection: {
      status: string;
      risk_level?: string;
      productive_z_score?: number;
      waste_delta_pct?: number;
      recent_avg_productive_minutes?: number;
      baseline_avg_productive_minutes?: number;
    };
  };
};

type RegimePayload = {
  regime_label: string;
  regime_score: number;
  details: {
    baseline_productive_mean?: number;
    recent_productive_mean?: number;
    baseline_waste_mean?: number;
    recent_waste_mean?: number;
    change_score?: number;
    avg_focus?: number;
    days_observed?: number;
  };
};

type ClassificationQualityPayload = {
  status: string;
  sample_size: number;
  proxy_accuracy?: number;
  avg_confidence?: number;
  fallback_rate?: number;
  class_distribution?: Record<string, number>;
};

type RankedSchedulePayload = {
  model_type: string;
  regime: string;
  forecast_count: number;
  ranked_blocks: {
    start_time: string;
    end_time: string;
    hour: number;
    tradeoff_score: number;
    confidence: number;
    suggested_task: string;
    tradeoff: {
      focus_gain: number;
      consistency: number;
      fatigue_cost: number;
      waste_risk: number;
    };
  }[];
};

type DecisionRecommendPayload = {
  context: {
    hour: number;
    productive_minutes_recent: number;
    waste_minutes_recent: number;
    neutral_minutes_recent: number;
    avg_focus_recent: number | null;
    regime: string;
  };
  recommended_actions: {
    action: string;
    score: number;
    predicted_uplift_pct: number;
    sample_size: number;
    why: string;
  }[];
};

type DecisionUpliftPayload = {
  status: string;
  baseline_reward?: number;
  action_uplift: {
    action: string;
    uplift_pct: number;
    confidence: number;
    treated_count: number;
  }[];
};

type InfluenceGraphPayload = {
  build_result: {
    status: string;
    edge_count: number;
  } | null;
  graph: {
    status: string;
    leverage_recommendations: {
      anchor_activity: string;
      influence_score: number;
      likely_impacted_activities: string[];
      recommendation: string;
    }[];
  };
};

type PrivacyStatusPayload = {
  local_only_training: boolean;
  local_llm_endpoint: string;
  cloud_training_enabled: boolean;
  note: string;
};

// --- Components ---

function GlassCard({ 
  title, 
  subtitle, 
  children, 
  className = "", 
  icon: Icon 
}: { 
  title: string; 
  subtitle?: string; 
  children: ReactNode; 
  className?: string; 
  icon?: any 
}) {
  return (
    <div className={`glass-pane rounded-3xl p-6 ${className}`}>
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400">{title}</h3>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {Icon && (
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/50 text-slate-400 shadow-sm border border-slate-100">
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

function MetricTile({ label, value, subvalue, type = "blue" }: { label: string; value: string | number; subvalue?: string; type?: "blue" | "emerald" | "rose" | "violet" }) {
  const colors = {
    blue: "text-blue-600 bg-blue-50/50 border-blue-100",
    emerald: "text-emerald-600 bg-emerald-50/50 border-emerald-100",
    rose: "text-rose-600 bg-rose-50/50 border-rose-100",
    violet: "text-violet-600 bg-violet-50/50 border-violet-100",
  };

  return (
    <div className={`rounded-3xl border p-5 transition-all hover:scale-[1.02] ${colors[type]}`}>
      <p className="text-[10px] font-bold uppercase tracking-[0.1em] opacity-80">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-tight">{value}</p>
      {subvalue && <p className="mt-1 text-xs font-medium opacity-70">{subvalue}</p>}
    </div>
  );
}

function SectionHeading({ title, icon: Icon }: { title: string; icon: any }) {
  return (
    <div className="mb-6 mt-12 flex items-center gap-2 border-b border-slate-100 pb-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white">
        <Icon className="h-4 w-4" />
      </div>
      <h2 className="text-xl font-bold tracking-tight text-slate-900">{title}</h2>
    </div>
  );
}

// --- Main View ---

export default function ZenithDashboard() {
  const [analytics, setAnalytics] = useState<AnalyticsPayload | null>(null);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [regime, setRegime] = useState<RegimePayload | null>(null);
  const [quality, setQuality] = useState<ClassificationQualityPayload | null>(null);
  const [rankedSchedule, setRankedSchedule] = useState<RankedSchedulePayload | null>(null);
  const [decisionRecommend, setDecisionRecommend] = useState<DecisionRecommendPayload | null>(null);
  const [decisionUplift, setDecisionUplift] = useState<DecisionUpliftPayload | null>(null);
  const [influenceGraph, setInfluenceGraph] = useState<InfluenceGraphPayload | null>(null);
  const [privacyStatus, setPrivacyStatus] = useState<PrivacyStatusPayload | null>(null);
  const [manualLog, setManualLog] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/analytics/');
        if (!response.ok) throw new Error('API Sync failed');
        const data = await response.json();
        setAnalytics(data);
        setAnalyticsError(null);
      } catch (err) {
        setAnalyticsError('Primary analytics sync offline.');
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 60000); // Poll every 60s
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const fetchAdvanced = async () => {
      try {
        const endpoints = [
          'http://127.0.0.1:8000/api/analytics/regime/',
          'http://127.0.0.1:8000/api/analytics/classification-quality/',
          'http://127.0.0.1:8000/api/schedule/ranked/',
          'http://127.0.0.1:8000/api/decision/recommend/',
          'http://127.0.0.1:8000/api/decision/uplift/',
          'http://127.0.0.1:8000/api/graph/influence/?rebuild=1',
          'http://127.0.0.1:8000/api/privacy/status/'
        ];
        const res = await Promise.all(endpoints.map(e => fetch(e).then(r => r.ok ? r.json() : null)));
        setRegime(res[0]);
        setQuality(res[1]);
        setRankedSchedule(res[2]);
        setDecisionRecommend(res[3]);
        setDecisionUplift(res[4]);
        setInfluenceGraph(res[5]);
        setPrivacyStatus(res[6]);
      } catch (e) { console.error("Advanced fetch failed", e); }
    };
    fetchAdvanced();
  }, []);

  const averageFocus = useMemo(() => {
    const values = (analytics?.weekly_trend ?? []).map(v => v.avg_focus).filter((v): v is number => v !== null);
    return values.length ? (values.reduce((s,v) => s+v, 0) / values.length).toFixed(1) : "0";
  }, [analytics]);

  const handleManualSubmit = async (e: any) => {
    e.preventDefault();
    if (!manualLog.trim()) return;
    setIsSubmitting(true);
    try {
      await fetch('http://127.0.0.1:8000/ingest/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: 'Manual Entry', duration_minutes: 60, metadata: { raw_text: manualLog } }),
      });
      setManualLog('');
    } finally { setIsSubmitting(false); }
  };

  return (
    <div className="min-h-screen px-6 py-10 lg:px-12">
      {/* --- Global Header --- */}
      <header className="mb-12 flex flex-col justify-between gap-8 lg:flex-row lg:items-end">
        <div>
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-950 text-white shadow-lg">
              <Command className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.4em] text-slate-400">Personal Strategic Intelligence</p>
              <h1 className="text-4xl font-black tracking-tight text-slate-900">ZENITH <span className="text-emerald-500">I.E.</span></h1>
            </div>
          </div>
          <p className="max-w-2xl text-lg font-medium text-slate-500">
            Cognitive optimization active. Analyzing neural behavior patterns in <span className="text-slate-900">real-time</span>.
          </p>
        </div>

        <div className="flex gap-4">
          <div className="glass-pane rounded-3xl px-6 py-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">System Accuracy</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{quality?.proxy_accuracy ? `${(quality.proxy_accuracy * 100).toFixed(0)}%` : "--"}</p>
          </div>
          <div className="glass-pane rounded-3xl px-6 py-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Total Volume</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{analytics?.week_analysis.total_minutes ?? 0}m</p>
          </div>
          <div className="glass-pane rounded-3xl border-emerald-100 bg-emerald-50/40 px-6 py-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600">Avg Performance</p>
            <p className="mt-1 text-2xl font-bold text-emerald-700">{averageFocus}</p>
          </div>
        </div>
      </header>

      {analyticsError && (
        <div className="mb-8 flex items-center gap-3 rounded-2xl border border-rose-100 bg-rose-50/50 p-4 text-sm font-medium text-rose-600">
          <AlertCircle className="h-4 w-4" /> {analyticsError}
        </div>
      )}

      {/* --- Primary Metrics Grid --- */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <GlassCard title="Real-time Pulse" subtitle="Current session metrics" icon={Activity} className="animate-in">
          <div className="grid grid-cols-2 gap-4">
            <MetricTile label="Productive" value={`${analytics?.today_analysis.productive_minutes ?? 0}m`} type="emerald" />
            <MetricTile label="Waste" value={`${analytics?.today_analysis.waste_minutes ?? 0}m`} type="rose" />
            <MetricTile label="Neutral" value={`${analytics?.today_analysis.neutral_minutes ?? 0}m`} type="blue" />
            <MetricTile label="Avg Focus" value={analytics?.today_analysis.avg_focus_score ?? "--"} type="violet" />
          </div>
          <div className="mt-6 rounded-2xl bg-white/50 p-4 text-xs font-medium text-slate-500 border border-slate-100">
             Top efficiency drain: <span className="text-slate-900 italic">"{analytics?.today_analysis.top_waste_activity ?? 'none identified'}"</span>
          </div>
        </GlassCard>

        <GlassCard title="Strategic Forecast" subtitle="24hr Probabilistic Model" icon={Target} className="animate-in [animation-delay:0.1s]">
          <div className="h-48 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={analytics?.ml_phase1.probabilistic_forecast ?? []}>
                <defs>
                   <linearGradient id="colorFocus" x1="0" y1="0" x2="0" y2="1">
                     <stop offset="5%" stopColor="#10b981" stopOpacity={0.1}/>
                     <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                   </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: '#94a3b8'}} />
                <YAxis hide domain={[0, 10]} />
                <Tooltip 
                  contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)', fontSize: '12px' }} 
                  itemStyle={{ fontWeight: 'bold' }}
                />
                <Area type="monotone" dataKey="p50" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorFocus)" />
                <Area type="monotone" dataKey="p90" stroke="#10b981" strokeWidth={0} fillOpacity={0.05} fill="#10b981" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest text-center">Confidence Interval: High</p>
        </GlassCard>

        <GlassCard title="Trajectory" subtitle="Weekly Performance Trend" icon={TrendingUp} className="animate-in [animation-delay:0.2s]">
          <div className="h-48 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={analytics?.weekly_trend ?? []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: '#94a3b8'}} />
                <YAxis hide />
                <Tooltip contentStyle={{ borderRadius: '12px', border: 'none', fontSize: '11px' }} />
                <Line type="monotone" dataKey="avg_focus" stroke="#6366f1" strokeWidth={3} dot={{ r: 4, fill: '#6366f1', strokeWidth: 2, stroke: '#fff' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        <GlassCard title="Neural Split" subtitle="Composition of focus" icon={Search} className="animate-in [animation-delay:0.3s]">
           <div className="h-48 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={analytics?.category_breakdown ?? []}
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="minutes"
                >
                  <Cell fill="#10b981" />
                  <Cell fill="#3b82f6" />
                  <Cell fill="#f43f5e" />
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>
      </div>

      {/* --- Strategic Command Row --- */}
      <SectionHeading title="Strategic Control" icon={Zap} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <GlassCard title="LLM Strategic Intel" subtitle={`Source: Local ${analytics?.assistant_insights_source ?? 'Model'}`} icon={Cpu}>
          <div className="space-y-4">
            {(analytics?.assistant_insights ?? []).map((msg, i) => (
              <div key={i} className="flex gap-3 animate-in" style={{ animationDelay: `${i * 0.15}s` }}>
                <div className="mt-1 h-3 w-3 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
                <p className="text-sm font-medium leading-relaxed text-slate-700">{msg}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard title="Optimal Routine Slots" subtitle="Bayesian Schedule Ranking" icon={Clock}>
          <div className="space-y-3">
            {(rankedSchedule?.ranked_blocks ?? []).slice(0, 4).map((block, i) => (
              <div key={i} className="group relative rounded-2xl border border-slate-100 bg-white/40 p-3 transition-colors hover:bg-white hover:border-emerald-200">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-bold text-slate-800 tracking-tight">
                    {new Date(block.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} — Peak State
                  </p>
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">SCR: {block.tradeoff_score}</span>
                </div>
                <p className="mt-1 text-xs font-medium text-emerald-600">{block.suggested_task}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard title="Manual Neural Sync" subtitle="Subjective event overwrite" icon={Lock}>
          <form onSubmit={handleManualSubmit} className="space-y-3">
             <textarea
              value={manualLog}
              onChange={(e) => setManualLog(e.target.value)}
              placeholder="Inject subjective performance data... (e.g. 'Highly focused coding 60m')"
              className="min-h-[100px] w-full rounded-2xl border border-slate-200 bg-white/30 p-4 text-sm outline-none transition-all placeholder:text-slate-400 focus:bg-white focus:border-slate-900 focus:ring-4 focus:ring-slate-50"
            />
            <button
              disabled={isSubmitting}
              type="submit"
              className="w-full rounded-2xl bg-slate-900 py-4 text-sm font-bold text-white transition-all hover:bg-slate-800 disabled:opacity-50 active:scale-[0.98]"
            >
              {isSubmitting ? "Processing Signal..." : "Sync Signal to Brain"}
            </button>
          </form>
        </GlassCard>
      </div>

      {/* --- System Health & Logic Row --- */}
      <SectionHeading title="Performance Logic" icon={ShieldCheck} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <GlassCard title="Behavioral Regime">
           <div className="flex flex-col items-center justify-center py-4 text-center">
              <span className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-400">Current Phase</span>
              <p className="text-3xl font-black text-slate-900">{regime?.regime_label ?? "Calibrating..."}</p>
              <div className="mt-4 h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                <div className="h-full bg-emerald-500 transition-all" style={{ width: `${(regime?.regime_score ?? 0) * 10}%` }} />
              </div>
           </div>
        </GlassCard>

        <GlassCard title="Policy Analysis">
           <div className="space-y-3">
             {(decisionRecommend?.recommended_actions ?? []).slice(0, 2).map((a, i) => (
               <div key={i} className="rounded-xl bg-violet-50/50 p-3 border border-violet-100">
                 <p className="text-xs font-bold text-violet-700">{a.action}</p>
                 <p className="mt-0.5 text-[10px] font-medium text-violet-500">Exp. Uplift: +{a.predicted_uplift_pct}%</p>
               </div>
             ))}
           </div>
        </GlassCard>

        <GlassCard title="Privacy Protocol">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-emerald-600">
              <ShieldCheck className="h-4 w-4" /> LOCAL-ONLY ENGINE
            </div>
            <p className="text-xs font-medium leading-relaxed text-slate-500">
              Inference endpoint: <code className="text-[10px] text-slate-900">{privacyStatus?.local_llm_endpoint ?? "127.0.0.1:11434"}</code>. 
              Zero persistent cloud outbound signals detected.
            </p>
          </div>
        </GlassCard>

        <GlassCard title="Activity Graph">
           <div className="space-y-2">
             <p className="text-xs font-bold text-slate-400 uppercase">Anchor Points</p>
             {(influenceGraph?.graph?.leverage_recommendations ?? []).slice(0, 2).map((l, i) => (
               <div key={i} className="rounded-xl border border-slate-100 p-2 text-[10px] font-medium text-slate-600">
                 <span className="text-slate-900 font-bold">{l.anchor_activity}:</span> {l.recommendation}
               </div>
             ))}
           </div>
        </GlassCard>
      </div>

      <footer className="mt-20 border-t border-slate-100 pt-8 pb-12 text-center">
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-300">ZENITH INTELLIGENCE • RELEASE 1.0.0</p>
      </footer>
    </div>
  );
}
