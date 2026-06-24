import type {
  Job,
  JobListResponse,
  SystemStatus,
  AnalyticsResponse,
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: 'no-store',
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchJobs(page = 1, pageSize = 50): Promise<JobListResponse> {
  return apiFetch(`/jobs?page=${page}&page_size=${pageSize}`);
}

export async function fetchJob(id: string): Promise<Job> {
  return apiFetch(`/jobs/${id}`);
}

export async function approveJob(id: string): Promise<void> {
  await apiFetch(`/jobs/${id}/approve`, { method: 'POST' });
}

export async function rejectJob(id: string): Promise<void> {
  await apiFetch(`/jobs/${id}/reject`, { method: 'POST' });
}

export async function analyzeJob(payload: {
  pr_url?: string;
  diff_content?: string;
  repo_name: string;
  pr_number?: number;
}): Promise<{ job_id: string; status: string }> {
  return apiFetch('/jobs/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  return apiFetch('/system/status');
}

export async function pauseSystem(): Promise<void> {
  await apiFetch('/system/pause', { method: 'POST' });
}

export async function resumeSystem(): Promise<void> {
  await apiFetch('/system/resume', { method: 'POST' });
}

export async function stopSystem(): Promise<void> {
  await apiFetch('/system/stop', { method: 'POST' });
}

export async function fetchGithub(): Promise<{ jobs_created: number; job_ids: string[] }> {
  return apiFetch('/system/fetch-github', { method: 'POST' });
}

export async function fetchAnalytics(): Promise<AnalyticsResponse> {
  return apiFetch('/analytics');
}
