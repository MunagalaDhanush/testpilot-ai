export interface AgentTrace {
  id: string;
  job_id: string;
  agent_name: string;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  created_at: string;
}

export interface GeneratedTest {
  id: string;
  job_id: string;
  test_type: 'unit' | 'integration' | 'api';
  file_content: string;
  file_path: string;
  pass_count: number;
  fail_count: number;
  coverage_delta: number;
  repair_attempts: number;
  created_at: string;
}

export type JobStatus =
  | 'queued'
  | 'processing'
  | 'awaiting_review'
  | 'completed'
  | 'rejected'
  | 'failed';

export type RiskLevel = 'high' | 'medium' | 'low' | 'critical';

export interface Job {
  id: string;
  pr_url: string;
  repo_name: string;
  pr_number: number;
  pr_title?: string;
  diff_content?: string;
  status: JobStatus;
  risk_level?: RiskLevel;
  final_summary?: string;
  tests_generated: number;
  pass_count: number;
  fail_count: number;
  coverage_delta: number;
  human_approved?: boolean | null;
  human_reviewed_at?: string | null;
  source: string;
  created_at: string;
  updated_at: string;
  traces: AgentTrace[];
  generated_tests: GeneratedTest[];
}

export interface JobListStats {
  total_tests_generated: number;
  avg_pass_rate?: number | null;
  avg_coverage_delta?: number | null;
}

export interface JobListResponse {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
  stats: JobListStats;
}

export interface SystemStatus {
  paused: boolean;
  stopped: boolean;
  active: boolean;
  active_jobs: number;
  queued_jobs: number;
  awaiting_review: number;
}

export interface AnalyticsPassRatePoint {
  date: string;
  pass_rate: number;
  total_jobs: number;
}

export interface AnalyticsRiskItem {
  risk_level: string;
  count: number;
}

export interface AnalyticsAgentPerf {
  agent_name: string;
  model_used: string;
  avg_latency_ms: number;
  run_count: number;
}

export interface AnalyticsModelTokens {
  job_id: string;
  date: string;
  haiku_tokens: number;
  sonnet_tokens: number;
}

export interface AnalyticsResponse {
  pass_rate_over_time: AnalyticsPassRatePoint[];
  risk_distribution: AnalyticsRiskItem[];
  agent_performance: AnalyticsAgentPerf[];
  model_tokens_per_job: AnalyticsModelTokens[];
}
