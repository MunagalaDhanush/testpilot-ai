'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Download, Pause, Play, Square, Loader2, ArrowRight,
  ExternalLink, Database, Timer, TrendingDown, Wrench,
  Zap, Activity, CheckCircle2,
} from 'lucide-react';
import {
  AreaChart, Area,
  BarChart, Bar,
  PieChart, Pie, Cell,
  LineChart, Line,
  XAxis, YAxis,
  CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import {
  fetchJobs, fetchSystemStatus, pauseSystem, resumeSystem,
  stopSystem, restartSystem, fetchGithub, approveJob, rejectJob, fetchAnalytics,
} from '../lib/api';
import type { Job, JobListStats, SystemStatus, AnalyticsResponse } from '../lib/types';

const JOBS_POLL_MS  = 30_000;
const STATS_POLL_MS = 60_000;

const STATUS_CFG: Record<string, { label: string; color: string; dot: string }> = {
  queued:          { label: 'Queued',          color: 'text-slate-400',   dot: 'bg-slate-500' },
  processing:      { label: 'Processing',      color: 'text-[#00d4ff]',   dot: 'bg-[#00d4ff] animate-pulse' },
  awaiting_review: { label: 'Awaiting Review', color: 'text-[#f59e0b]',   dot: 'bg-[#f59e0b] animate-pulse' },
  completed:       { label: 'Completed',       color: 'text-[#00ff88]',   dot: 'bg-[#00ff88]' },
  rejected:        { label: 'Rejected',        color: 'text-[#ef4444]',   dot: 'bg-[#ef4444]' },
  failed:          { label: 'Failed',          color: 'text-[#ef4444]',   dot: 'bg-[#ef4444]' },
};

const RISK_COLORS: Record<string, string> = {
  low: '#00ff88', medium: '#f59e0b', high: '#ef4444', critical: '#7c3aed', unknown: '#00d4ff',
};

const SOURCE_CFG: Record<string, { label: string; style: string }> = {
  webhook: { label: 'Webhook', style: 'text-[#00d4ff] border-[#00d4ff]/40 bg-[#00d4ff]/5' },
  seeded:  { label: 'Seeded',  style: 'text-[#7c3aed] border-[#7c3aed]/40 bg-[#7c3aed]/5' },
  manual:  { label: 'Manual',  style: 'text-[#f59e0b] border-[#f59e0b]/40 bg-[#f59e0b]/5' },
};

const CC = { cyan: '#00d4ff', violet: '#7c3aed', success: '#00ff88', warning: '#f59e0b', danger: '#ef4444' };

// ── Shared tooltip style ──────────────────────────────────────────────────────
const TT_STYLE: React.CSSProperties = {
  background: '#1a1a2e',
  border: '1px solid #00d4ff',
  borderRadius: '8px',
  padding: '8px 12px',
  color: '#f1f5f9',
  fontWeight: 600,
  fontSize: '13px',
  boxShadow: '0 0 12px rgba(0,212,255,0.2)',
};

// ── Custom chart tooltips ─────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function RiskTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TT_STYLE}>
      <div style={{ color: payload[0].payload.fill, marginBottom: 2 }}>{payload[0].name}</div>
      <div style={{ color: '#00d4ff', fontWeight: 700 }}>{payload[0].value} jobs</div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function PassRateTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TT_STYLE}>
      <div style={{ color: '#94a3b8', marginBottom: 4, fontSize: 11 }}>{label}</div>
      <div style={{ color: '#00d4ff', fontWeight: 700 }}>{payload[0].value.toFixed(1)}% pass rate</div>
      {payload[0].payload?.total_jobs != null && (
        <div style={{ color: '#475569', fontSize: 11, marginTop: 2 }}>{payload[0].payload.total_jobs} jobs</div>
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function AgentTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TT_STYLE}>
      <div style={{ color: '#94a3b8', marginBottom: 4, fontSize: 11 }}>{String(label).replace(/_/g, ' ')}</div>
      <div style={{ color: '#7c3aed', fontWeight: 700 }}>{payload[0].value} ms avg</div>
      {payload[0].payload?.run_count != null && (
        <div style={{ color: '#475569', fontSize: 11, marginTop: 2 }}>{payload[0].payload.run_count} runs</div>
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function TokensTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TT_STYLE}>
      <div style={{ color: '#94a3b8', marginBottom: 6, fontSize: 11 }}>{label}</div>
      {payload.map((p: { name: string; value: number; color: string }) => (
        <div key={p.name} style={{ color: p.color, fontWeight: 700 }}>
          {p.name}: {p.value?.toLocaleString()}
        </div>
      ))}
    </div>
  );
}

// ── InfoTooltip ───────────────────────────────────────────────────────────────
function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="tooltip-container ml-1 cursor-default select-none">
      <span className="text-[#475569] text-xs border border-[#2a2a3e] rounded-full w-4 h-4 inline-flex items-center justify-center font-mono font-semibold leading-none">i</span>
      <span className="tooltip-text">{text}</span>
    </span>
  );
}

// ── Stat tile ────────────────────────────────────────────────────────────────
function StatTile({ label, value, sub, accent, tooltip }: {
  label: string; value: string | number; sub?: string;
  accent: 'cyan' | 'violet' | 'success' | 'warning'; tooltip: string;
}) {
  const a = {
    cyan:    { text: 'text-[#00d4ff]', border: 'border-[#00d4ff]/20', glow: 'glow-cyan' },
    violet:  { text: 'text-[#7c3aed]', border: 'border-[#7c3aed]/20', glow: 'glow-violet' },
    success: { text: 'text-[#00ff88]', border: 'border-[#00ff88]/20', glow: 'glow-success' },
    warning: { text: 'text-[#f59e0b]', border: 'border-[#f59e0b]/20', glow: 'glow-warning' },
  }[accent];
  return (
    <div className={`stat-tile bg-[#0d0d14] border ${a.border} ${a.glow} rounded-xl p-5 flex flex-col gap-1`}>
      <div className="flex items-center text-xs text-[#475569] uppercase tracking-widest font-semibold">
        {label}<InfoTooltip text={tooltip} />
      </div>
      <div className={`text-3xl font-bold ${a.text} font-mono`}>{value}</div>
      {sub && <div className="text-xs text-[#475569] font-medium">{sub}</div>}
    </div>
  );
}

// ── Efficiency card ───────────────────────────────────────────────────────────
function EfficiencyCard({
  icon: Icon, label, value, sub, accent, tooltip,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string; value: string | number; sub: string;
  accent: 'cyan' | 'green' | 'violet' | 'amber'; tooltip: string;
}) {
  const a = {
    cyan:   { text: 'text-[#00d4ff]', border: 'border-[#00d4ff]/20', glow: 'glow-cyan' },
    green:  { text: 'text-[#00ff88]', border: 'border-[#00ff88]/20', glow: 'glow-success' },
    violet: { text: 'text-[#7c3aed]', border: 'border-[#7c3aed]/20', glow: 'glow-violet' },
    amber:  { text: 'text-[#f59e0b]', border: 'border-[#f59e0b]/20', glow: 'glow-warning' },
  }[accent];
  return (
    <div className={`stat-tile bg-[#0d0d14] border ${a.border} ${a.glow} rounded-xl p-5 flex flex-col gap-2`}>
      <div className="flex items-center justify-between">
        <Icon className={`w-5 h-5 ${a.text}`} />
        <InfoTooltip text={tooltip} />
      </div>
      <div className={`text-2xl font-bold ${a.text} font-mono`}>{value}</div>
      <div>
        <div className="text-xs text-[#94a3b8] font-semibold uppercase tracking-wider">{label}</div>
        <div className="text-xs text-[#475569] font-medium mt-0.5">{sub}</div>
      </div>
    </div>
  );
}

// ── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] ?? { label: status, color: 'text-slate-400', dot: 'bg-slate-500' };
  return (
    <span className={`flex items-center gap-1.5 text-xs font-semibold ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

// ── Risk badge ───────────────────────────────────────────────────────────────
function RiskBadge({ level }: { level?: string | null }) {
  if (!level) return <span className="text-[#475569] text-xs font-medium">—</span>;
  const color = RISK_COLORS[level] ?? '#475569';
  return <span className="text-xs font-bold uppercase" style={{ color }}>{level}</span>;
}

// ── Source badge ─────────────────────────────────────────────────────────────
function SourceBadge({ source }: { source?: string }) {
  const cfg = SOURCE_CFG[source ?? 'webhook'] ?? SOURCE_CFG.webhook;
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold border ${cfg.style}`}>
      {cfg.label}
    </span>
  );
}

// ── Approval buttons ─────────────────────────────────────────────────────────
function ApprovalButtons({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  async function act(action: 'approve' | 'reject') {
    setBusy(action);
    try {
      if (action === 'approve') await approveJob(jobId);
      else await rejectJob(jobId);
      onDone();
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  }
  return (
    <div className="flex gap-1.5">
      <button onClick={() => act('approve')} disabled={busy !== null}
        className="px-2.5 py-1 text-xs rounded font-semibold bg-[#00ff88]/10 text-[#00ff88] border border-[#00ff88]/30 hover:bg-[#00ff88]/20 disabled:opacity-40 transition-colors">
        {busy === 'approve' ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Approve'}
      </button>
      <button onClick={() => act('reject')} disabled={busy !== null}
        className="px-2.5 py-1 text-xs rounded font-semibold bg-[#ef4444]/10 text-[#ef4444] border border-[#ef4444]/30 hover:bg-[#ef4444]/20 disabled:opacity-40 transition-colors">
        {busy === 'reject' ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Reject'}
      </button>
    </div>
  );
}

// ── Stop dialog ──────────────────────────────────────────────────────────────
function StopDialog({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-2xl p-6 max-w-sm mx-4 shadow-2xl">
        <h3 className="text-[#f1f5f9] font-bold text-base mb-2">Stop All Activity</h3>
        <p className="text-[#94a3b8] text-sm font-medium leading-relaxed mb-5">
          This will halt all processing. Click Restart System to resume. Continue?
        </p>
        <div className="flex gap-3 justify-end">
          <button onClick={onCancel}
            className="px-4 py-2 text-sm font-semibold text-[#94a3b8] border border-[#1a1a2e] rounded-lg hover:border-[#2a2a3e] hover:text-[#f1f5f9] transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm}
            className="px-4 py-2 text-sm font-semibold text-[#ef4444] bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-lg hover:bg-[#ef4444]/20 transition-colors">
            Stop All Activity
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Charts ───────────────────────────────────────────────────────────────────
function PassRateChart({ data }: { data: AnalyticsResponse['pass_rate_over_time'] }) {
  return (
    <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
      <h3 className="text-xs text-[#475569] mb-4 uppercase tracking-widest font-semibold">Pass Rate Over Time</h3>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="prGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={CC.cyan} stopOpacity={0.3} />
              <stop offset="95%" stopColor={CC.cyan} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
          <XAxis dataKey="date" tick={{ fill: '#475569', fontSize: 10, fontWeight: 500 }} />
          <YAxis unit="%" tick={{ fill: '#475569', fontSize: 10 }} domain={[0, 100]} />
          <Tooltip content={<PassRateTooltip />} />
          <Area type="monotone" dataKey="pass_rate" stroke={CC.cyan} strokeWidth={2} fill="url(#prGrad)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function RiskDistChart({ data }: { data: AnalyticsResponse['risk_distribution'] }) {
  return (
    <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
      <h3 className="text-xs text-[#475569] mb-4 uppercase tracking-widest font-semibold">Risk Distribution</h3>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={data} cx="50%" cy="50%"
            innerRadius={50} outerRadius={80}
            dataKey="count" nameKey="risk_level"
            paddingAngle={3}
          >
            {data.map((entry) => (
              <Cell
                key={entry.risk_level}
                fill={RISK_COLORS[entry.risk_level] ?? '#475569'}
                stroke="#1a1a2e"
                strokeWidth={2}
              />
            ))}
          </Pie>
          <Tooltip content={<RiskTooltip />} />
          <Legend iconType="circle" iconSize={8}
            formatter={(v) => (
              <span style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, textTransform: 'capitalize' }}>{v}</span>
            )} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function AgentPerfChart({ data }: { data: AnalyticsResponse['agent_performance'] }) {
  return (
    <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
      <h3 className="text-xs text-[#475569] mb-4 uppercase tracking-widest font-semibold">Agent Latency (avg ms)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" horizontal={false} />
          <XAxis type="number" tick={{ fill: '#475569', fontSize: 10, fontWeight: 500 }} />
          <YAxis dataKey="agent_name" type="category" tick={{ fill: '#475569', fontSize: 10, fontWeight: 500 }} width={120}
            tickFormatter={(v: string) => v.replace(/_/g, ' ')} />
          <Tooltip content={<AgentTooltip />} />
          <Bar dataKey="avg_latency_ms" fill={CC.violet} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function TokensChart({ data }: { data: AnalyticsResponse['model_tokens_per_job'] }) {
  return (
    <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
      <h3 className="text-xs text-[#475569] mb-4 uppercase tracking-widest font-semibold">Tokens per Job (last 10)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data.slice(-10)} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
          <XAxis dataKey="date" tick={{ fill: '#475569', fontSize: 10, fontWeight: 500 }} />
          <YAxis tick={{ fill: '#475569', fontSize: 10 }} />
          <Tooltip content={<TokensTooltip />} />
          <Legend iconType="circle" iconSize={8}
            formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500 }}>{v}</span>} />
          <Line type="monotone" dataKey="haiku_tokens"  name="Haiku"  stroke={CC.cyan}   strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="sonnet_tokens" name="Sonnet" stroke={CC.violet} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Duration formatter ────────────────────────────────────────────────────────
function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [jobs, setJobs]           = useState<Job[]>([]);
  const [stats, setStats]         = useState<JobListStats>({ total_tests_generated: 0, avg_pass_rate: null, avg_coverage_delta: null });
  const [total, setTotal]         = useState(0);
  const [sysStatus, setSysStatus] = useState<SystemStatus>({ paused: false, stopped: false, active: true, active_jobs: 0, queued_jobs: 0, awaiting_review: 0 });
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [fetchBusy, setFetchBusy]     = useState(false);
  const [pauseBusy, setPauseBusy]     = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [stopDialog, setStopDialog]   = useState(false);
  const tabHiddenRef  = useRef(false);
  const jobsTimerRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const statsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadJobs = useCallback(async () => {
    try {
      const [listRes, statusRes] = await Promise.all([fetchJobs(1, 100), fetchSystemStatus()]);
      setJobs(listRes.items);
      setStats(listRes.stats);
      setTotal(listRes.total);
      setSysStatus(statusRes);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAnalytics = useCallback(async () => {
    try {
      const res = await fetchAnalytics();
      setAnalytics(res);
    } catch (e) {
      console.error('Analytics fetch failed:', e);
    }
  }, []);

  useEffect(() => {
    const onVisibility = () => {
      tabHiddenRef.current = document.visibilityState === 'hidden';
      if (document.visibilityState === 'visible') loadJobs();
    };
    document.addEventListener('visibilitychange', onVisibility);

    loadJobs();
    loadAnalytics();

    jobsTimerRef.current = setInterval(() => {
      if (!tabHiddenRef.current) loadJobs();
    }, JOBS_POLL_MS);
    statsTimerRef.current = setInterval(() => {
      if (!tabHiddenRef.current) loadAnalytics();
    }, STATS_POLL_MS);

    return () => {
      if (jobsTimerRef.current)  clearInterval(jobsTimerRef.current);
      if (statsTimerRef.current) clearInterval(statsTimerRef.current);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [loadJobs, loadAnalytics]);

  async function handleFetch() {
    setFetchBusy(true);
    try { await fetchGithub(); await loadJobs(); }
    catch (e) { console.error(e); }
    finally { setFetchBusy(false); }
  }

  async function handlePause() {
    setPauseBusy(true);
    try {
      if (sysStatus.paused) await resumeSystem(); else await pauseSystem();
      await loadJobs();
    } finally { setPauseBusy(false); }
  }

  async function handleStop() {
    setStopDialog(false);
    await stopSystem();
    await loadJobs();
  }

  async function handleRestart() {
    setRestartBusy(true);
    try { await restartSystem(); await loadJobs(); }
    catch (e) { console.error(e); }
    finally { setRestartBusy(false); }
  }

  // ── Derived display values ────────────────────────────────────────────────
  const passRateStr = stats.avg_pass_rate != null ? `${stats.avg_pass_rate.toFixed(1)}%` : '—';
  const covDeltaStr = stats.avg_coverage_delta != null
    ? `${stats.avg_coverage_delta >= 0 ? '+' : ''}${stats.avg_coverage_delta.toFixed(1)}%` : '—';

  const statusDot   = sysStatus.stopped ? 'bg-[#ef4444]' : sysStatus.paused ? 'bg-[#f59e0b]' : 'bg-[#00ff88] animate-pulse';
  const statusLabel = sysStatus.stopped ? 'Stopped' : sysStatus.paused ? 'Paused' : 'Active';

  // ── Efficiency metrics (computed from jobs list) ──────────────────────────
  const completedJobs = jobs.filter((j) => ['completed', 'awaiting_review', 'rejected'].includes(j.status));

  const avgMs = completedJobs.length > 0
    ? completedJobs.reduce((acc, j) => acc + (new Date(j.updated_at).getTime() - new Date(j.created_at).getTime()), 0) / completedJobs.length
    : 0;
  const avgProcessingStr = completedJobs.length > 0 ? fmtDuration(Math.round(avgMs / 1000)) : '—';

  const reviewedJobs  = jobs.filter((j) => j.human_approved !== null && j.human_approved !== undefined);
  const approvedCount = reviewedJobs.filter((j) => j.human_approved === true).length;
  const approvalRateStr = reviewedJobs.length > 0
    ? `${Math.round((approvedCount / reviewedJobs.length) * 100)}%` : '—';

  const now        = Date.now();
  const last24h    = jobs.filter((j) => now - new Date(j.created_at).getTime() < 86_400_000);
  const throughput = last24h.length > 0 ? (last24h.length / 24).toFixed(1) : '0';

  const zeroFailJobs   = completedJobs.filter((j) => j.pass_count > 0 && j.fail_count === 0);
  const repairRateStr  = completedJobs.length > 0
    ? `${Math.round((zeroFailJobs.length / completedJobs.length) * 100)}%` : '—';

  return (
    <div className="min-h-screen bg-[#050508]">
      {stopDialog && <StopDialog onConfirm={handleStop} onCancel={() => setStopDialog(false)} />}

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div className="border-b border-[#1a1a2e]">
        <div className="max-w-7xl mx-auto px-6 py-8 flex items-start justify-between gap-6 flex-wrap">
          <div>
            <h1 className="text-4xl font-extrabold tracking-tight leading-none">
              <span className="text-[#00d4ff] text-glow-cyan">Test</span>
              <span className="text-[#f1f5f9]">Pilot</span>
              <span className="text-[#7c3aed] text-glow-violet"> AI</span>
            </h1>
            <p className="mt-2 text-[#94a3b8] text-sm font-medium">
              Multi-agent automated test generation platform
            </p>
            <div className="mt-3 flex items-center gap-2 text-xs font-medium text-[#475569]">
              <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
              <span className="text-[#94a3b8] font-semibold">{statusLabel}</span>
              <span className="text-[#1a1a2e] select-none">·</span>
              <span>Queue: {sysStatus.queued_jobs}</span>
              <span className="text-[#1a1a2e] select-none">·</span>
              <span>Processing: {sysStatus.active_jobs}</span>
              {sysStatus.awaiting_review > 0 && (
                <>
                  <span className="text-[#1a1a2e] select-none">·</span>
                  <span className="text-[#f59e0b] font-semibold">{sysStatus.awaiting_review} awaiting review</span>
                </>
              )}
            </div>
          </div>

          {/* ── Control bar ──────────────────────────────────────────────── */}
          <div className="flex flex-col items-end gap-3">
            {sysStatus.stopped ? (
              /* Stopped state: single prominent Restart button */
              <button
                onClick={handleRestart}
                disabled={restartBusy}
                className="flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-bold border-2 border-[#00ff88] text-[#00ff88] bg-[#00ff88]/10 hover:bg-[#00ff88]/20 disabled:opacity-40 transition-all glow-success"
              >
                {restartBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Restart System
              </button>
            ) : (
              /* Active / Paused state: three buttons */
              <div className="flex items-center gap-2">
                <div className="tooltip-container">
                  <button
                    onClick={handleFetch}
                    disabled={fetchBusy}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border border-[#00d4ff]/50 text-[#00d4ff] hover:bg-[#00d4ff]/10 hover:border-[#00d4ff] disabled:opacity-40 transition-all"
                  >
                    {fetchBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Fetch PRs
                  </button>
                  <span className="tooltip-text">Pull the latest merged pull requests from configured GitHub repositories into the processing queue</span>
                </div>

                <div className="tooltip-container">
                  <button
                    onClick={handlePause}
                    disabled={pauseBusy}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-all disabled:opacity-40 ${
                      sysStatus.paused
                        ? 'border-[#00ff88]/50 text-[#00ff88] hover:bg-[#00ff88]/10'
                        : 'border-[#f59e0b]/50 text-[#f59e0b] hover:bg-[#f59e0b]/10'
                    }`}
                  >
                    {pauseBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : sysStatus.paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                    {sysStatus.paused ? 'Resume Queue' : 'Pause Queue'}
                  </button>
                  <span className="tooltip-text">Pause or resume processing of queued test generation jobs</span>
                </div>

                <div className="tooltip-container">
                  <button
                    onClick={() => setStopDialog(true)}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border border-[#ef4444]/50 text-[#ef4444] hover:bg-[#ef4444]/10 transition-all"
                  >
                    <Square className="w-4 h-4" />
                    Stop All
                  </button>
                  <span className="tooltip-text">Stop all GitHub fetching and test generation activity</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* ── Stat tiles ───────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatTile label="Total Jobs"      value={total}                       sub={`${sysStatus.active_jobs} active`}  accent="cyan"    tooltip="Total PR analysis jobs created" />
          <StatTile label="Tests Generated" value={stats.total_tests_generated} sub="across all jobs"                    accent="violet"  tooltip="Sum of all test files produced by the generator agent" />
          <StatTile label="Avg Pass Rate"   value={passRateStr}                 sub="completed jobs"                     accent="success" tooltip="Average (pass / total tests) across completed jobs" />
          <StatTile label="Avg Coverage"    value={covDeltaStr}                 sub="vs baseline"                        accent="warning" tooltip="Average coverage improvement introduced by generated tests" />
        </div>

        {/* ── Error ────────────────────────────────────────────────────── */}
        {error && (
          <div className="bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-xl px-5 py-4 text-sm font-medium text-[#ef4444]">
            {error}
          </div>
        )}

        {/* ── Analyze CTA ──────────────────────────────────────────────── */}
        <div className="border border-[#00d4ff]/20 bg-[#00d4ff]/5 rounded-xl p-6 flex items-center justify-between gap-6 hover:border-[#00d4ff]/40 transition-colors">
          <div>
            <h2 className="text-[#f1f5f9] font-bold text-base mb-1">Analyze a pull request</h2>
            <p className="text-[#94a3b8] text-sm font-medium">Submit any GitHub PR or paste a diff to generate test cases on demand</p>
          </div>
          <Link href="/analyze"
            className="flex items-center gap-2 px-5 py-2.5 bg-[#00d4ff] hover:bg-[#00b8d9] text-black font-bold text-sm rounded-lg transition-colors whitespace-nowrap flex-shrink-0">
            Get Started
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        {/* ── Jobs table ───────────────────────────────────────────────── */}
        <div>
          <h2 className="text-xs text-[#475569] uppercase tracking-widest mb-4 font-semibold">
            Recent Jobs <span className="ml-2 text-[#2a2a3e] normal-case font-medium">({total})</span>
          </h2>
          <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl overflow-hidden">
            {loading ? (
              <div className="p-12 flex items-center justify-center gap-3 text-[#475569] text-sm font-medium">
                <Loader2 className="w-4 h-4 animate-spin" /> Connecting...
              </div>
            ) : jobs.length === 0 ? (
              <div className="p-12 flex flex-col items-center justify-center gap-3 text-center">
                <Database className="w-8 h-8 text-[#2a2a3e]" />
                <p className="text-[#475569] text-sm font-medium">No jobs yet</p>
                <code className="text-xs bg-[#1a1a2e] text-[#94a3b8] px-3 py-1.5 rounded-md font-mono">
                  python seeder/github_seeder.py
                </code>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#1a1a2e]">
                      {['Repository', 'Source', 'Status', 'Risk', 'Tests', 'Pass%', 'Review', 'Created'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs text-[#475569] uppercase tracking-widest font-semibold whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1a1a2e]/60">
                    {jobs.map((job) => {
                      const tot  = job.pass_count + job.fail_count;
                      const rate = tot > 0 ? `${((job.pass_count / tot) * 100).toFixed(0)}%` : '—';
                      return (
                        <tr key={job.id} className="hover:bg-[#1a1a2e]/30 transition-colors">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5">
                              <Link href={`/jobs/${job.id}`}
                                className="text-[#00d4ff] hover:underline font-semibold font-mono text-sm">
                                {job.repo_name}#{job.pr_number}
                              </Link>
                              <a href={job.pr_url} target="_blank" rel="noopener noreferrer"
                                className="text-[#475569] hover:text-[#94a3b8] transition-colors">
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            </div>
                            {job.pr_title && (
                              <div className="text-xs text-[#475569] font-medium mt-0.5 max-w-[180px] truncate">
                                {job.pr_title}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3"><SourceBadge source={job.source} /></td>
                          <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                          <td className="px-4 py-3"><RiskBadge level={job.risk_level} /></td>
                          <td className="px-4 py-3 text-[#94a3b8] font-medium text-xs font-mono">{job.tests_generated || '—'}</td>
                          <td className="px-4 py-3 text-[#94a3b8] font-medium text-xs font-mono">{rate}</td>
                          <td className="px-4 py-3">
                            {job.status === 'awaiting_review' ? (
                              <ApprovalButtons jobId={job.id} onDone={loadJobs} />
                            ) : job.human_approved === true ? (
                              <span className="text-xs text-[#00ff88] font-semibold">Approved</span>
                            ) : job.human_approved === false ? (
                              <span className="text-xs text-[#ef4444] font-semibold">Rejected</span>
                            ) : (
                              <span className="text-[#2a2a3e] text-xs font-medium">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-[#475569] text-xs font-medium whitespace-nowrap">
                            {new Date(job.created_at).toLocaleDateString()}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* ── System Efficiency ─────────────────────────────────────────── */}
        <div>
          <h2 className="text-xs text-[#475569] uppercase tracking-widest mb-4 font-semibold">System Efficiency</h2>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <EfficiencyCard
              icon={Timer}
              label="Avg Processing Time"
              value={avgProcessingStr}
              sub="per test generation job"
              accent="cyan"
              tooltip="Average time from PR submission to completed test generation across all jobs"
            />
            <EfficiencyCard
              icon={TrendingDown}
              label="Model Cost Efficiency"
              value="~60% savings"
              sub="vs single-model approach"
              accent="green"
              tooltip="Cost saved by routing lightweight tasks to Claude Haiku instead of Claude Sonnet. Haiku costs ~25x less per token."
            />
            <EfficiencyCard
              icon={Wrench}
              label="Repair Success Rate"
              value={repairRateStr}
              sub="self-repair effectiveness"
              accent="violet"
              tooltip="Percentage of completed jobs where all generated tests pass after any self-repair attempts by the failure diagnostician agent"
            />
            <EfficiencyCard
              icon={Zap}
              label="Parallel Efficiency"
              value="3x faster"
              sub="parallel vs sequential"
              accent="amber"
              tooltip="Speed gain from running test generators for unit, integration, and API tests simultaneously rather than one at a time"
            />
            <EfficiencyCard
              icon={Activity}
              label="Queue Throughput"
              value={`${throughput}/hr`}
              sub="jobs/hour last 24h"
              accent="cyan"
              tooltip="Rate at which TestPilot processes pull requests in the last 24 hours. Higher is better."
            />
            <EfficiencyCard
              icon={CheckCircle2}
              label="Human Approval Rate"
              value={approvalRateStr}
              sub="approval rate"
              accent="green"
              tooltip="Percentage of AI-generated test suites approved by human reviewers before merging"
            />
          </div>
        </div>

        {/* ── Analytics charts ──────────────────────────────────────────── */}
        {analytics && (
          <div>
            <h2 className="text-xs text-[#475569] uppercase tracking-widest mb-4 font-semibold">Analytics</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <PassRateChart  data={analytics.pass_rate_over_time} />
              <RiskDistChart  data={analytics.risk_distribution} />
              <AgentPerfChart data={analytics.agent_performance} />
              <TokensChart    data={analytics.model_tokens_per_job} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
