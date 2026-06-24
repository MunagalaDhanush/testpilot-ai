'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import {
  ChevronLeft, Clock, Loader2, CheckCircle2, XCircle,
  FileText, FlaskConical, ExternalLink,
} from 'lucide-react';
import { fetchJob, approveJob, rejectJob } from '../../../lib/api';
import type { Job, AgentTrace, GeneratedTest } from '../../../lib/types';

// ── Constants ─────────────────────────────────────────────────────────────────
const LIVE_POLL_MS = 2_000;
const STATIC_POLL_MS = 10_000;
const TERMINAL = new Set(['completed', 'failed', 'rejected', 'awaiting_review']);

const AGENT_ORDER = [
  'context_collector',
  'risk_classifier',
  'test_strategist',
  'test_generator_unit',
  'test_generator_integration',
  'test_generator_api',
  'failure_diagnoser',
  'pr_summarizer',
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(iso: string) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(iso));
}
function fmtMs(ms: number) { return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`; }
function isHaiku(model: string) { return model.includes('haiku'); }

// ── StatusBadge ───────────────────────────────────────────────────────────────
const STATUS_CFG: Record<string, { label: string; color: string; dot: string }> = {
  queued:          { label: 'Queued',          color: 'text-[#94a3b8]',   dot: 'bg-slate-500' },
  processing:      { label: 'Processing',      color: 'text-[#00d4ff]',   dot: 'bg-[#00d4ff] animate-pulse' },
  awaiting_review: { label: 'Awaiting Review', color: 'text-[#f59e0b]',   dot: 'bg-[#f59e0b] animate-pulse' },
  completed:       { label: 'Completed',       color: 'text-[#00ff88]',   dot: 'bg-[#00ff88]' },
  rejected:        { label: 'Rejected',        color: 'text-[#ef4444]',   dot: 'bg-[#ef4444]' },
  failed:          { label: 'Failed',          color: 'text-[#ef4444]',   dot: 'bg-[#ef4444]' },
};
function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] ?? { label: status, color: 'text-[#94a3b8]', dot: 'bg-slate-500' };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border border-current/20 bg-current/5 ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

// ── RiskBadge ────────────────────────────────────────────────────────────────
const RISK_COLORS: Record<string, string> = { low: '#00ff88', medium: '#f59e0b', high: '#ef4444', critical: '#7c3aed' };
function RiskBadge({ level }: { level?: string | null }) {
  if (!level) return null;
  const color = RISK_COLORS[level] ?? '#475569';
  return (
    <span className="inline-flex px-2.5 py-1 rounded-md text-xs font-bold uppercase border"
      style={{ color, borderColor: `${color}40`, background: `${color}10` }}>
      {level} risk
    </span>
  );
}

// ── Approval gate ─────────────────────────────────────────────────────────────
function ApprovalGate({ jobId, onDone }: { jobId: string; onDone: () => void }) {
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
    <div className="bg-[#f59e0b]/5 border border-[#f59e0b]/30 rounded-xl p-6 glow-warning">
      <div className="flex items-start gap-4">
        <div className="w-8 h-8 rounded-full bg-[#f59e0b]/20 border border-[#f59e0b]/30 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Clock className="w-4 h-4 text-[#f59e0b]" />
        </div>
        <div className="flex-1">
          <div className="text-[#f59e0b] font-bold text-sm mb-1">Awaiting Human Review</div>
          <p className="text-[#94a3b8] text-sm font-medium leading-relaxed mb-5">
            The pipeline has completed. Review the generated tests and PR summary below,
            then approve to post the summary comment to GitHub, or reject to discard.
          </p>
          <div className="flex gap-3">
            <button onClick={() => act('approve')} disabled={busy !== null}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#00ff88]/10 text-[#00ff88] border border-[#00ff88]/30 hover:bg-[#00ff88]/20 disabled:opacity-40 transition-colors text-sm font-bold">
              {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              Approve and Post to GitHub
            </button>
            <button onClick={() => act('reject')} disabled={busy !== null}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#ef4444]/10 text-[#ef4444] border border-[#ef4444]/30 hover:bg-[#ef4444]/20 disabled:opacity-40 transition-colors text-sm font-bold">
              {busy === 'reject' ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
              Reject
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Token bar ─────────────────────────────────────────────────────────────────
function TokenBar({ input, output, maxTotal }: { input: number; output: number; maxTotal: number }) {
  const total = input + output;
  const inputPct = maxTotal > 0 ? (input / maxTotal) * 100 : 0;
  const outputPct = maxTotal > 0 ? (output / maxTotal) * 100 : 0;
  return (
    <div className="mt-2">
      <div className="flex gap-3 text-xs font-semibold font-mono mb-1">
        <span className="text-[#00d4ff]">In: {input.toLocaleString()}</span>
        <span className="text-[#7c3aed]">Out: {output.toLocaleString()}</span>
        <span className="text-[#475569]">Total: {total.toLocaleString()}</span>
      </div>
      <div className="w-full h-1.5 bg-[#1a1a2e] rounded-full overflow-hidden flex">
        <div className="h-full bg-[#00d4ff] rounded-l-full transition-all duration-500"
          style={{ width: `${inputPct}%` }} />
        <div className="h-full bg-[#7c3aed] transition-all duration-500"
          style={{ width: `${outputPct}%` }} />
      </div>
    </div>
  );
}

// ── Live pipeline ─────────────────────────────────────────────────────────────
function LivePipeline({ traces, isLive }: { traces: AgentTrace[]; isLive: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  const completedNames = new Set(traces.map((t) => t.agent_name));
  const lastCompleted = traces.length > 0 ? traces[traces.length - 1].agent_name : null;
  const runningIndex = lastCompleted ? AGENT_ORDER.indexOf(lastCompleted) + 1 : 0;
  const runningAgent = isLive && runningIndex < AGENT_ORDER.length ? AGENT_ORDER[runningIndex] : null;

  const maxTotal = Math.max(...traces.map((t) => (t.input_tokens || 0) + (t.output_tokens || 0)), 1);

  // Check parallel execution
  const contextTrace = traces.find((t) => t.agent_name === 'context_collector');
  const riskTrace    = traces.find((t) => t.agent_name === 'risk_classifier');
  const isParallel   = contextTrace && riskTrace && Math.abs(
    new Date(contextTrace.created_at).getTime() - new Date(riskTrace.created_at).getTime()
  ) < 5000;

  useEffect(() => {
    if (!runningAgent) return;
    const iv = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(iv);
  }, [runningAgent]);

  useEffect(() => { setElapsed(0); }, [runningAgent]);

  return (
    <div className="space-y-2">
      {AGENT_ORDER.map((agentName, idx) => {
        const trace = traces.find((t) => t.agent_name === agentName);
        const isCompleted = completedNames.has(agentName);
        const isRunning = agentName === runningAgent;
        const displayName = agentName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        const haiku = trace ? isHaiku(trace.model_used) : false;
        const modelColor = haiku ? 'text-[#00d4ff] bg-[#00d4ff]/10 border-[#00d4ff]/30' : 'text-[#7c3aed] bg-[#7c3aed]/10 border-[#7c3aed]/30';
        const modelLabel = haiku ? 'Haiku' : 'Sonnet';

        const showParallel = isParallel && idx === 1 && (isCompleted || isRunning);

        return (
          <div key={agentName}>
            {showParallel && (
              <div className="flex items-center gap-3 my-2 px-2">
                <div className="flex-1 h-px bg-[#1a1a2e]" />
                <span className="text-xs text-[#475569] font-medium whitespace-nowrap">Parallel execution</span>
                <div className="flex-1 h-px bg-[#1a1a2e]" />
              </div>
            )}
            <div className={`rounded-xl border p-4 transition-all duration-500 ${
              isCompleted
                ? 'border-[#00ff88]/30 bg-[#0d0d14]'
                : isRunning
                ? 'border-[#00d4ff]/50 bg-gradient-to-r from-[#00d4ff]/5 to-transparent'
                : 'border-[#1a1a2e] bg-[#0d0d14]'
            }`}>
              <div className="flex items-start gap-3">
                {/* Icon */}
                <div className="mt-0.5 flex-shrink-0">
                  {isCompleted ? (
                    <CheckCircle2 className="w-5 h-5 text-[#00ff88]" />
                  ) : isRunning ? (
                    <Loader2 className="w-5 h-5 text-[#00d4ff] animate-spin" />
                  ) : (
                    <Clock className="w-5 h-5 text-[#475569]" />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className={`font-semibold text-sm ${
                    isCompleted ? 'text-[#f1f5f9]' : isRunning ? 'text-[#00d4ff]' : 'text-[#475569]'
                  }`}>
                    {displayName}
                  </div>

                  {isCompleted && trace && (
                    <TokenBar
                      input={trace.input_tokens || 0}
                      output={trace.output_tokens || 0}
                      maxTotal={maxTotal}
                    />
                  )}

                  {isRunning && (
                    <div className="text-xs text-[#475569] font-medium mt-1">
                      Processing... {elapsed}s
                    </div>
                  )}

                  {!isCompleted && !isRunning && (
                    <div className="text-xs text-[#2a2a3e] font-medium mt-1">Waiting to start</div>
                  )}
                </div>

                {/* Right side */}
                {isCompleted && trace && (
                  <div className="text-right flex-shrink-0">
                    <div className="text-[#f1f5f9] font-semibold font-mono text-sm">{fmtMs(trace.latency_ms)}</div>
                    <span className={`inline-flex mt-1 px-2 py-0.5 rounded text-xs font-semibold border ${modelColor}`}>
                      {modelLabel}
                    </span>
                  </div>
                )}
              </div>

              {/* Running progress bar */}
              {isRunning && (
                <div className="mt-3 h-0.5 bg-[#1a1a2e] rounded overflow-hidden">
                  <div className="h-full w-1/3 bg-[#00d4ff] rounded progress-indeterminate" />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Coverage chart ────────────────────────────────────────────────────────────
function CoverageChart({ tests }: { tests: GeneratedTest[] }) {
  const data = tests.filter((t) => t.coverage_delta > 0).map((t) => ({
    name: t.file_path.split('/').pop()?.replace('.py', '') ?? t.file_path,
    delta: parseFloat(t.coverage_delta.toFixed(1)),
    type: t.test_type,
  }));
  if (data.length === 0) return null;
  const typeColors: Record<string, string> = { unit: '#00d4ff', integration: '#7c3aed', api: '#00ff88' };
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" vertical={false} />
        <XAxis dataKey="name" tick={{ fill: '#475569', fontSize: 10, fontWeight: 500 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => `+${v}%`} />
        <Tooltip
          contentStyle={{ background: '#0d0d14', border: '1px solid #1a1a2e', borderRadius: 8, fontSize: 11, fontWeight: 500 }}
          formatter={(v: number) => [`+${v}%`, 'Coverage Delta']}
        />
        <Bar dataKey="delta" radius={[4, 4, 0, 0]}>
          {data.map((e, i) => <Cell key={i} fill={typeColors[e.type] ?? '#475569'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Test file viewer ──────────────────────────────────────────────────────────
function TestFileViewer({ tests }: { tests: GeneratedTest[] }) {
  const [active, setActive] = useState(0);
  if (tests.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <FlaskConical className="w-8 h-8 text-[#2a2a3e]" />
        <p className="text-[#475569] text-sm font-medium">No tests generated</p>
      </div>
    );
  }
  const cur = tests[active];
  const tabColor: Record<string, string> = {
    unit: 'text-[#00d4ff] border-[#00d4ff]/40',
    integration: 'text-[#7c3aed] border-[#7c3aed]/40',
    api: 'text-[#00ff88] border-[#00ff88]/40',
  };
  return (
    <div>
      <div className="flex gap-1 mb-3 flex-wrap">
        {tests.map((t, i) => {
          const name = t.file_path.split('/').pop() ?? t.file_path;
          const tot = t.pass_count + t.fail_count;
          const rate = tot === 0 ? null : Math.round((t.pass_count / tot) * 100);
          return (
            <button key={t.id} onClick={() => setActive(i)}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors font-mono ${
                i === active
                  ? `${tabColor[t.test_type] ?? 'text-[#94a3b8] border-[#475569]'} bg-white/5`
                  : 'text-[#475569] border-[#1a1a2e] hover:border-[#475569] hover:text-[#94a3b8]'
              }`}>
              {name}
              {rate !== null && (
                <span className={`ml-1.5 font-semibold ${rate === 100 ? 'text-[#00ff88]' : 'text-[#f59e0b]'}`}>
                  {rate}%
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-3 px-3 py-2 bg-[#0a0a0f] border border-[#1a1a2e] rounded-t-lg text-xs font-semibold font-mono text-[#475569]">
        <span className="text-[#94a3b8] truncate">{cur.file_path}</span>
        <span className="ml-auto uppercase text-[10px]">{cur.test_type}</span>
        <span className="text-[#00ff88]">{cur.pass_count} pass</span>
        {cur.fail_count > 0 && <span className="text-[#ef4444]">{cur.fail_count} fail</span>}
        {cur.coverage_delta > 0 && <span className="text-[#00d4ff]">+{cur.coverage_delta.toFixed(1)}% cov</span>}
      </div>
      <div className="rounded-b-lg overflow-hidden border border-t-0 border-[#1a1a2e] max-h-[480px] overflow-y-auto">
        <SyntaxHighlighter language="python" style={vscDarkPlus}
          customStyle={{ margin: 0, background: '#0a0a0f', fontSize: '11px', lineHeight: '1.6' }}
          showLineNumbers lineNumberStyle={{ color: '#2a2a3e', fontSize: '10px' }}>
          {cur.file_content || '# (empty)'}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

// ── PR Summary ────────────────────────────────────────────────────────────────
function PrSummary({ markdown }: { markdown?: string | null }) {
  if (!markdown) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <FileText className="w-8 h-8 text-[#2a2a3e]" />
        <p className="text-[#475569] text-sm font-medium">No summary generated yet</p>
      </div>
    );
  }
  return (
    <div className="prose-dark">
      <ReactMarkdown
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const lang = match ? match[1] : 'text';
            if (!className) {
              return <code {...props} className={className}>{children}</code>;
            }
            return (
              <SyntaxHighlighter language={lang} style={vscDarkPlus}
                customStyle={{ margin: '0.75em 0', borderRadius: 8, fontSize: '12px' }}>
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            );
          },
        }}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function JobDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params?.id as string;
  const isLiveParam = searchParams?.get('live') === 'true';

  const [job, setJob]         = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const timerRef              = useRef<ReturnType<typeof setInterval> | null>(null);

  const isLive = isLiveParam || job?.status === 'processing';

  const load = useCallback(async (): Promise<boolean> => {
    if (!id) return true;
    try {
      const data = await fetchJob(id);
      setJob(data);
      setError(null);
      return TERMINAL.has(data.status);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load().then((done) => {
      if (!done) {
        const ms = isLiveParam ? LIVE_POLL_MS : STATIC_POLL_MS;
        timerRef.current = setInterval(async () => {
          const done = await load();
          if (done && timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
        }, ms);
      }
    });
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [load, isLiveParam]);

  const passCount = job?.pass_count ?? 0;
  const failCount = job?.fail_count ?? 0;
  const totalT    = passCount + failCount;
  const passRate  = totalT > 0 ? `${((passCount / totalT) * 100).toFixed(0)}%` : null;

  return (
    <div className="min-h-screen bg-[#050508]">
      {/* Nav */}
      <div className="border-b border-[#1a1a2e] sticky top-0 bg-[#050508]/95 backdrop-blur z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-1.5 text-[#475569] hover:text-[#94a3b8] text-sm font-semibold transition-colors">
            <ChevronLeft className="w-4 h-4" />
            Dashboard
          </Link>
          <span className="text-[#1a1a2e] select-none">|</span>
          <span className="text-[#475569] text-xs font-mono">{id?.slice(0, 8)}...</span>
          {isLive && (
            <span className="ml-2 flex items-center gap-1.5 text-xs font-semibold text-[#00d4ff]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00d4ff] animate-pulse" />
              Live
            </span>
          )}
        </div>
      </div>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {loading && (
          <div className="py-20 flex items-center justify-center gap-3 text-[#475569]">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm font-medium">Loading job...</span>
          </div>
        )}

        {error && !loading && (
          <div className="bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-xl px-6 py-8 text-center">
            <XCircle className="w-8 h-8 text-[#ef4444] mx-auto mb-3" />
            <p className="text-[#ef4444] text-sm font-semibold mb-1">Failed to load job</p>
            <p className="text-[#475569] text-xs font-mono">{error}</p>
          </div>
        )}

        {!loading && !error && job && (
          <>
            {/* Header card */}
            <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[#f1f5f9] font-bold text-lg font-mono">{job.repo_name}</span>
                    <span className="text-[#475569] font-mono font-semibold">#{job.pr_number}</span>
                    {job.risk_level && <RiskBadge level={job.risk_level} />}
                    <StatusBadge status={job.status} />
                  </div>
                  {job.pr_title && <p className="text-[#94a3b8] text-sm font-medium">{job.pr_title}</p>}
                  <a href={job.pr_url} target="_blank" rel="noopener noreferrer"
                    className="text-[#00d4ff]/60 hover:text-[#00d4ff] text-xs font-mono font-medium transition-colors inline-flex items-center gap-1">
                    {job.pr_url}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
                <div className="text-right text-xs font-medium text-[#475569] shrink-0">
                  <div>Created {fmt(job.created_at)}</div>
                  <div className="mt-0.5 text-[#2a2a3e]">Updated {fmt(job.updated_at)}</div>
                  {job.human_approved === true && <div className="mt-1 text-[#00ff88] font-semibold">Approved</div>}
                  {job.human_approved === false && <div className="mt-1 text-[#ef4444] font-semibold">Rejected</div>}
                </div>
              </div>
              <div className="mt-5 pt-4 border-t border-[#1a1a2e] grid grid-cols-2 sm:grid-cols-5 gap-4">
                {[
                  { label: 'Tests',      value: job.tests_generated || 0,      color: 'text-[#00d4ff]' },
                  { label: 'Passed',     value: passCount,                      color: 'text-[#00ff88]' },
                  { label: 'Failed',     value: failCount,                      color: 'text-[#ef4444]' },
                  { label: 'Pass Rate',  value: passRate ?? '—',                color: 'text-[#f59e0b]' },
                  { label: 'Agents',     value: (job.traces ?? []).length,      color: 'text-[#7c3aed]' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center">
                    <div className={`text-xl font-bold font-mono ${color}`}>{value}</div>
                    <div className="text-xs text-[#475569] mt-0.5 uppercase tracking-wider font-semibold">{label}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Approval gate */}
            {job.status === 'awaiting_review' && (
              <ApprovalGate jobId={job.id} onDone={() => load()} />
            )}

            {/* Live pipeline */}
            <section className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-xs text-[#475569] uppercase tracking-widest font-semibold">
                  Agent Pipeline
                  {isLive && <span className="ml-2 text-[#00d4ff] normal-case font-semibold">— Live</span>}
                </h2>
                <div className="flex items-center gap-4 text-xs font-medium text-[#475569]">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#00d4ff]" />Haiku
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#7c3aed]" />Sonnet
                  </span>
                </div>
              </div>
              <LivePipeline traces={job.traces ?? []} isLive={!!isLive} />
            </section>

            {/* Coverage chart */}
            {(job.generated_tests ?? []).some((t) => t.coverage_delta > 0) && (
              <section className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xs text-[#475569] uppercase tracking-widest font-semibold">Coverage Delta by File</h2>
                  <div className="flex gap-3 text-xs font-medium text-[#475569]">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-[#00d4ff]" />unit</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-[#7c3aed]" />integration</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-[#00ff88]" />api</span>
                  </div>
                </div>
                <CoverageChart tests={job.generated_tests ?? []} />
              </section>
            )}

            {/* Generated tests */}
            <section className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
              <h2 className="text-xs text-[#475569] uppercase tracking-widest font-semibold mb-4">Generated Tests</h2>
              <TestFileViewer tests={job.generated_tests ?? []} />
            </section>

            {/* PR Summary */}
            <section className="bg-[#0d0d14] border border-[#1a1a2e] rounded-xl p-6">
              <h2 className="text-xs text-[#475569] uppercase tracking-widest font-semibold mb-4">PR Summary</h2>
              <PrSummary markdown={job.final_summary} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
