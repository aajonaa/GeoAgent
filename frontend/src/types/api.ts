/**
 * Shared TypeScript contracts matching OreBOGAO's FastAPI backend and SSE protocol.
 */

export type UserRole = 'admin' | 'member';

export interface AuthSession {
  id: string;
  username: string;
  role: UserRole;
  csrf: string;
  email?: string | null;
  organization?: string | null;
  research_area?: string | null;
  must_change_password?: boolean;
}

export interface RegistrationUiConfig {
  mode: string;
  email_enabled: boolean;
  phone_binding_enabled: boolean;
  digits: number;
  cooldown: number;
  allowed_regions: readonly string[];
  default_region: string | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  generation: string;
  created: number;
  updated: number;
}

export interface FileManifestItem {
  name: string;
  size: number;
  sha256: string;
  origin?: Record<string, unknown> | null;
}

export interface ConversationFilesResponse {
  generation: string;
  files: FileManifestItem[];
}

export type RunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'cancelled'
  | 'incomplete'
  | 'budget_exhausted'
  | 'interrupted';

export interface ResearchPlan {
  objective: string;
  scope: string;
  materials: string;
  tools: string;
  deliverables: string;
  acceptance: string[];
}

export interface RunRecord {
  id: string;
  cid: string;
  query: string;
  status: RunStatus;
  answer: string;
  error: string;
  created: number;
  updated?: number;
  finished?: number | null;
  generation?: string | null;
  research_plan?: ResearchPlan | null;
}

export interface ConversationDetail extends ConversationSummary {
  runs: RunRecord[];
}

export interface ActiveTaskSummary {
  id: string;
  cid: string;
  title: string;
  query: string;
  status: RunStatus;
  created: number;
  elapsed_seconds: number;
}

export interface PendingInputRequest {
  id: string;
  cid: string;
  rid: string;
  title?: string;
  question: string;
  state: 'pending' | 'answered' | 'expired' | 'cancelled';
  options?: string[];
  created?: number;
}

export interface ActiveTasksResponse {
  tasks: ActiveTaskSummary[];
  requests: PendingInputRequest[];
}

export type RecoveryAction = 'follow_up' | 'derive' | 'resume' | 'retry' | 'inspect';

export type RecoveryVisualState = 'completed' | 'stopped' | 'failed' | 'partial';

export interface RecoverySpec {
  state: RecoveryVisualState;
  title: string;
  detail: string;
  actions: ReadonlyArray<readonly [RecoveryAction, string]>;
}

export interface ReleaseLedgerEntry {
  version: string;
  build: string;
  created?: string;
  summary?: string;
}

export interface ReleaseHistoryResponse {
  build: string;
  version: string | null;
  entries: ReleaseLedgerEntry[];
}

export interface TodoItem {
  id: string;
  text: string;
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
}

export type RunEvent =
  | { type: 'status'; status: RunStatus; message?: string; ts?: number }
  | { type: 'tool_start'; tool: string; call_id?: string; args?: Record<string, unknown>; ts?: number }
  | { type: 'tool_result'; tool: string; call_id?: string; ok: boolean; summary?: string; ts?: number }
  | { type: 'knowledge_sources'; items: Array<Record<string, unknown>>; ts?: number }
  | { type: 'plan_confirmed'; plan: ResearchPlan; ts?: number }
  | { type: 'skill_selected'; skill_id: string; score?: number; ts?: number }
  | { type: 'skill_loaded'; skill_id: string; ts?: number }
  | { type: 'todo_updated'; items: TodoItem[]; ts?: number }
  | { type: 'codeact_tool_call'; tool: string; ok: boolean; duration_ms?: number; ts?: number }
  | { type: 'subagent_started'; task_id: string; role?: string; ts?: number }
  | { type: 'subagent_finished'; task_id: string; status: string; ts?: number }
  | { type: 'finished'; status: RunStatus; answer?: string; error?: string; ts?: number }
  | { type: 'error'; message: string; code?: string; ts?: number };
