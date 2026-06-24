'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ChevronLeft, ArrowRight, Loader2 } from 'lucide-react';
import { analyzeJob } from '../../lib/api';

function parsePrUrl(url: string): { repo: string; pr: number } | null {
  const m = url.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/);
  if (!m) return null;
  return { repo: m[1], pr: parseInt(m[2], 10) };
}

export default function AnalyzePage() {
  const router = useRouter();
  const [tab, setTab] = useState<'url' | 'diff'>('url');

  // URL tab
  const [prUrl, setPrUrl]     = useState('');
  const parsed = parsePrUrl(prUrl);

  // Diff tab
  const [repo, setRepo]       = useState('');
  const [diff, setDiff]       = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      let payload: Parameters<typeof analyzeJob>[0];
      if (tab === 'url') {
        if (!parsed) { setSubmitError('Enter a valid GitHub PR URL'); setSubmitting(false); return; }
        payload = { pr_url: prUrl, repo_name: parsed.repo, pr_number: parsed.pr };
      } else {
        if (!repo.trim()) { setSubmitError('Repository name is required'); setSubmitting(false); return; }
        if (!diff.trim()) { setSubmitError('Diff content is required'); setSubmitting(false); return; }
        payload = { diff_content: diff, repo_name: repo.trim() };
      }
      const { job_id } = await analyzeJob(payload);
      router.push(`/jobs/${job_id}?live=true`);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Submission failed');
      setSubmitting(false);
    }
  }

  const inputBase = 'w-full bg-[#0d0d14] border border-[#2a2a3e] rounded-lg px-4 py-3 text-[#f1f5f9] font-medium text-sm placeholder:text-[#2a2a3e] focus:outline-none focus:border-[#00d4ff] transition-colors';

  return (
    <div className="min-h-screen bg-[#050508]">
      {/* Nav */}
      <div className="border-b border-[#1a1a2e]">
        <div className="max-w-3xl mx-auto px-6 py-4">
          <Link href="/" className="flex items-center gap-1.5 text-[#475569] hover:text-[#94a3b8] text-sm font-semibold transition-colors w-fit">
            <ChevronLeft className="w-4 h-4" />
            Dashboard
          </Link>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-[#f1f5f9] mb-2">Analyze a Pull Request</h1>
          <p className="text-[#94a3b8] font-medium text-sm leading-relaxed">
            Submit a GitHub PR URL or paste a raw diff to generate test cases and evaluate coverage
          </p>
        </div>

        {/* Form card */}
        <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-2xl p-6">
          {/* Tabs */}
          <div className="flex gap-1 mb-6 bg-[#050508] rounded-lg p-1 w-fit">
            {(['url', 'diff'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-4 py-2 rounded-md text-sm font-semibold transition-all ${
                  tab === t
                    ? 'bg-[#0d0d14] text-[#f1f5f9] border border-[#1a1a2e]'
                    : 'text-[#475569] hover:text-[#94a3b8]'
                }`}>
                {t === 'url' ? 'GitHub PR URL' : 'Paste Raw Diff'}
              </button>
            ))}
          </div>

          {tab === 'url' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[#475569] uppercase tracking-widest mb-2">
                  Pull Request URL
                </label>
                <input
                  type="url"
                  value={prUrl}
                  onChange={(e) => setPrUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo/pull/123"
                  className={`${inputBase} font-mono`}
                />
              </div>
              {parsed && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-[#050508] border border-[#1a1a2e] rounded-lg px-4 py-3">
                    <div className="text-xs text-[#475569] font-semibold uppercase tracking-wider mb-1">Repository</div>
                    <div className="text-[#94a3b8] font-mono text-sm font-semibold">{parsed.repo}</div>
                  </div>
                  <div className="bg-[#050508] border border-[#1a1a2e] rounded-lg px-4 py-3">
                    <div className="text-xs text-[#475569] font-semibold uppercase tracking-wider mb-1">PR Number</div>
                    <div className="text-[#94a3b8] font-mono text-sm font-semibold">#{parsed.pr}</div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[#475569] uppercase tracking-widest mb-2">
                  Repository (owner/repo)
                </label>
                <input
                  type="text"
                  value={repo}
                  onChange={(e) => setRepo(e.target.value)}
                  placeholder="fastapi/fastapi"
                  className={`${inputBase} font-mono`}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-[#475569] uppercase tracking-widest mb-2">
                  Git Diff Content
                </label>
                <textarea
                  value={diff}
                  onChange={(e) => setDiff(e.target.value)}
                  placeholder="Paste your git diff here..."
                  rows={20}
                  className={`${inputBase} font-mono text-xs resize-y`}
                />
              </div>
            </div>
          )}

          {submitError && (
            <div className="mt-4 bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-lg px-4 py-3 text-sm font-medium text-[#ef4444]">
              {submitError}
            </div>
          )}

          <button
            onClick={submit}
            disabled={submitting}
            className="mt-6 w-full flex items-center justify-center gap-2 px-6 py-3.5 bg-[#00d4ff] hover:bg-[#00b8d9] text-black font-bold text-sm rounded-xl transition-colors disabled:opacity-50">
            {submitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" />Submitting...</>
            ) : (
              <>Generate Tests<ArrowRight className="w-4 h-4" /></>
            )}
          </button>
        </div>

        {/* What happens next */}
        <div className="bg-[#0d0d14] border border-[#1a1a2e] rounded-2xl p-6">
          <h2 className="text-[#f1f5f9] font-bold text-base mb-5">What happens next</h2>
          <div className="space-y-5">
            {[
              {
                n: 1, title: 'Context Collection',
                desc: 'TestPilot reads your PR diff and identifies changed functions, APIs, and risk areas',
              },
              {
                n: 2, title: 'Test Generation',
                desc: 'Six AI agents collaborate to write unit, integration, and API tests tailored to your specific changes',
              },
              {
                n: 3, title: 'Execution and Review',
                desc: 'Tests run in an isolated sandbox. Results appear in real time as each agent completes',
              },
            ].map(({ n, title, desc }) => (
              <div key={n} className="flex gap-4">
                <div className="w-7 h-7 rounded-full border border-[#00d4ff]/40 text-[#00d4ff] flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5">
                  {n}
                </div>
                <div>
                  <div className="text-[#f1f5f9] font-semibold text-sm mb-1">{title}</div>
                  <div className="text-[#475569] text-sm font-medium leading-relaxed">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
