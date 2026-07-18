// Typed mirror of the gateway's REST/WS surface. The UI's only vocabulary.

export interface PlanNode {
  capability_id: string;
  origin: string;
  priority_band: "CRITICAL" | "REQUIRED" | "OPTIONAL" | "DEFERRED";
  confidence: number;
  group_id?: string;
  rank?: number;
}

export interface PlanView {
  plan_id: string;
  version: number;
  confidence: number;
  hash: string;
  determinism: Record<string, string | number>;
  nodes: Record<string, PlanNode>;
  edges: [string, string, string][]; // [type, from, to]
}

export interface WorkflowUnit {
  unit_id: string;
  node_id: string;
  capability_id: string;
  priority_band: string;
  gate_required: boolean;
}

export interface WorkflowView {
  workflow_id: string;
  hash: string;
  canonical_order: string[];
  levels: string[][];
  units: Record<string, WorkflowUnit>;
  edges: [string, string][];
}

export type UnitState = "pending" | "executing" | "succeeded" | "failed" | "not-executed";

export interface RunView {
  status: "active" | "completed" | "failed" | "cancelled";
  unit_state: Record<string, UnitState>;
}

export interface RequestView {
  request_id: string;
  intent: string;
  goals: string[];
  provenance: Record<string, string>;
  kernel_state: string;
  plan: PlanView | null;
  workflow: WorkflowView | null;
  run: RunView | null;
}

export interface SystemOverview {
  uptime_seconds: number;
  success_rate: number | null;
  components: {
    kernel: { active_requests: number; halted: boolean; log_records: number };
    communication: { topics: number; dead_letters: number };
    storage: { vault: string };
    execution: { executions: number };
  };
  requests: RequestView[];
  event_count: number;
  unwired: string[];
}

export interface BusEvent {
  seq: number;
  topic: string;
  observed_at?: number; // gateway arrival time (the OS itself is clockless)
  message: {
    event_id?: string;
    event_name?: string;
    request_id?: string | null;
    payload?: Record<string, unknown>;
    [key: string]: unknown;
  };
}
