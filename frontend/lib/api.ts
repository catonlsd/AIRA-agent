const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Citation = {
  source_type: string;
  title: string;
  url?: string | null;
  document_id?: number | null;
  chunk_id?: number | null;
  page?: number | null;
  snippet?: string | null;
};

export type ChatResponse = {
  answer: string;
  citations: Citation[];
  confidence: string;
  plan: {
    rewritten_query: string;
    needs_documents: boolean;
    needs_web: boolean;
    reason: string;
  };
};

export type AiraXAgent = {
  agent_name: string;
  description: string;
  role: string;
  responsibilities: string[];
  capabilities?: string[];
  name?: string;
  [key: string]: any;
};

export type AiraXTool = {
  tool_name: string;
  description: string;
  actions: string[];
  policy: Record<string, any>;
  examples: string[];
  name?: string;
  [key: string]: any;
};

export type AiraXApprovalContext = {
  type?: string;
  preflight_scope?: string;
  tool_name?: string;
  tool_action?: string;
  pending_action?: string;

  commit_message?: string | null;
  branch?: string;
  changed_files?: string;
  diff_summary?: string;

  target_remote?: string;
  target_branch?: string;
  status_branch?: string;
  remote_info?: string;
  last_commit?: string;
  recent_commits?: string;

  branch_success?: boolean;
  status_success?: boolean;
  diff_success?: boolean;
  status_branch_success?: boolean;
  remote_info_success?: boolean;
  last_commit_success?: boolean;
  recent_commits_success?: boolean;

  [key: string]: any;
};

export type AiraXApprovalResolution = {
  status?: string;
  previous_status?: string;
  action?: string;
  requested_at?: string;
  completed_at?: string;
  final_status?: string;
  final_decision?: string;
  error?: string;
  [key: string]: any;
};

export type AiraXApprovalRecoveryEvent = {
  reason?: string;
  action?: string;
  started_at?: string;
  recovered_at?: string;
  stale_after_seconds?: number;
  previous_resolution_status?: string;
  [key: string]: any;
};

export type AiraXCleanupAction = {
  reason: string;
  tool_name: string;
  tool_action: string;
  result?: {
    success?: boolean;
    command?: string;
    output?: string;
    error?: string;
    [key: string]: any;
  };
  [key: string]: any;
};

export type AiraXWorkflowStep = {
  id: number;
  title: string;
  description: string;
  status: string;
  assigned_agent: string;
  tool_name?: string | null;
  tool_action?: string | null;
  tool_payload?: any;
  result?: string | null;
  error?: string | null;
  [key: string]: any;
};

export type AiraXWorkflowRun = {
  run_id: string;
  user_goal: string;
  status: string;
  decision: string;
  final_answer: string | null;
  current_step: number | null;
  retry_count: number;

  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;

  requires_approval: boolean;
  pending_action?: string;

  approval_context?: AiraXApprovalContext;
  approval_context_type?: string;

  approval_in_progress?: boolean;
  approval_resolution?: AiraXApprovalResolution;
  approval_resolution_status?: string;
  approval_resolution_action?: string;

  approval_stale_recovered?: boolean;
  approval_recovery_events?: AiraXApprovalRecoveryEvent[];
  approval_recovery_count?: number;
  has_approval_recovery?: boolean;

  cleanup_actions?: AiraXCleanupAction[];
  cleanup_count?: number;
  has_cleanup?: boolean;

  step_count: number;
  log_count: number;
  plan: AiraXWorkflowStep[];
  execution_outputs: any[];
  memory: Record<string, any>;
  workflow_logs?: any[];
  workflow_summary?: Record<string, any>;

  success?: boolean;
  error?: string;
  [key: string]: any;
};

export type AiraXRunResponse = AiraXWorkflowRun;

export type AiraXRunsResponse = {
  run_count: number;
  runs: AiraXWorkflowRun[];
};

export type AiraXAgentsResponse = {
  agent_count: number;
  agents: AiraXAgent[];
};

export type AiraXToolsResponse = {
  tool_count: number;
  tools: AiraXTool[];
};

export type AiraXAgentResponse = {
  success: boolean;
  agent_name: string;
  agent: AiraXAgent;
  error?: string;
};

export type AiraXToolResponse = {
  success: boolean;
  tool_name: string;
  tool: AiraXTool;
  error?: string;
};

export type AiraXRunDetailResponse = {
  success: boolean;
  run: AiraXWorkflowRun;
  error?: string;
};

export type AiraXDeletedRunSummary = {
  run_id: string;
  user_goal?: string;
  status?: string;
  decision?: string;
  final_answer?: string | null;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  [key: string]: any;
};

export type AiraXDeleteRunResponse = {
  success: boolean;
  deleted_run_id?: string;
  deleted_run?: AiraXDeletedRunSummary;
  remaining_run_count?: number;

  error?: string;
  run_id?: string;
  current_status?: string;
  decision?: string;
  approval_in_progress?: boolean;
  approval_resolution?: AiraXApprovalResolution;
  workflow?: AiraXWorkflowRun;

  [key: string]: any;
};

export type AiraXSafeCleanupSkippedRun = {
  run_id: string;
  user_goal?: string;
  status?: string;
  decision?: string;
  reason?: string;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  approval_in_progress?: boolean;
  [key: string]: any;
};

export type AiraXSafeCleanupResponse = {
  success: boolean;
  deleted_count: number;
  skipped_count: number;
  deleted_runs: AiraXDeletedRunSummary[];
  skipped_runs: AiraXSafeCleanupSkippedRun[];
  remaining_run_count: number;
  safe_statuses: string[];

  error?: string;
  [key: string]: any;
};

export type AiraXOverviewResponse = {
  platform: string;
  focus: string;
  status: string;
  agent_count: number;
  tool_count: number;
  agents?: AiraXAgent[];
  tools?: AiraXTool[];
  workflow_metrics: {
    total_runs: number;
    completed_runs: number;
    failed_runs: number;
    requires_approval_runs: number;
    rejected_runs: number;

    total_retries: number;
    total_tool_calls: number;
    total_logs: number;

    git_preflight_runs?: number;
    git_write_preflight_runs?: number;
    git_push_preflight_runs?: number;

    cleanup_runs?: number;
    total_cleanup_actions?: number;

    approval_in_progress_runs?: number;
    approval_resolved_runs?: number;
    approval_approved_runs?: number;
    approval_rejected_runs?: number;
    approval_resume_failed_runs?: number;

    stale_approval_recovery_runs?: number;
    approval_stale_recovered_runs?: number;
    total_approval_recovery_events?: number;

    latest_runs: AiraXWorkflowRun[];
  };
};

export type AssistantResponseType =
  | "casual_chat"
  | "capability_help"
  | "general_answer"
  | "document_research"
  | "web_research"
  | "execution_result"
  | "approval_required"
  | "workflow_followup"
  | "multi_task"
  | "clarification"
  | "error";

export function isMultiTaskResponse(
  response: AssistantRunResponse
): response is AssistantRunResponse & {
  response_type: "multi_task";
  metadata: AssistantRunResponse["metadata"] & {
    task_count?: number;
    failed_tasks?: number[];
    response_types?: string[];
  };
} {
  return response.response_type === "multi_task";
}

export type AssistantWorkflow = Partial<AiraXWorkflowRun> & {
  run_id?: string;
  status?: string;
  decision?: string;
  final_answer?: string | null;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: AiraXApprovalContext;
  plan?: AiraXWorkflowStep[];
  execution_outputs?: any[];
  memory?: Record<string, any>;
  workflow_logs?: any[];
  workflow_summary?: Record<string, any>;
  [key: string]: any;
};

export type AssistantRunResponse = {
  response_type: AssistantResponseType;
  answer: string;
  citations: Citation[];
  workflow?: AssistantWorkflow | null;
  run_id?: string | null;
  metadata: Record<string, any>;
};

export function assistantWorkflowToAiraXRun(
  workflow?: AssistantWorkflow | null
): AiraXRunResponse | null {
  if (!workflow || !workflow.run_id) {
    return null;
  }

  return {
    run_id: workflow.run_id,
    user_goal: workflow.user_goal || workflow.workflow_summary?.user_goal || "",
    status: workflow.status || "unknown",
    decision: workflow.decision || "unknown",
    final_answer: workflow.final_answer ?? null,
    current_step: workflow.current_step ?? null,
    retry_count: workflow.retry_count ?? 0,
    created_at: workflow.created_at,
    updated_at: workflow.updated_at,
    completed_at: workflow.completed_at,
    requires_approval: workflow.requires_approval ?? false,
    pending_action: workflow.pending_action,
    approval_context: workflow.approval_context,
    approval_context_type: workflow.approval_context_type,
    approval_in_progress: workflow.approval_in_progress,
    approval_resolution: workflow.approval_resolution,
    approval_resolution_status: workflow.approval_resolution_status,
    approval_resolution_action: workflow.approval_resolution_action,
    approval_stale_recovered: workflow.approval_stale_recovered,
    approval_recovery_events: workflow.approval_recovery_events,
    approval_recovery_count: workflow.approval_recovery_count,
    has_approval_recovery: workflow.has_approval_recovery,
    cleanup_actions: workflow.cleanup_actions,
    cleanup_count: workflow.cleanup_count,
    has_cleanup: workflow.has_cleanup,
    step_count: workflow.step_count ?? workflow.plan?.length ?? 0,
    log_count: workflow.log_count ?? workflow.workflow_logs?.length ?? 0,
    plan: workflow.plan || [],
    execution_outputs: workflow.execution_outputs || [],
    memory: workflow.memory || {},
    workflow_logs: workflow.workflow_logs || [],
    workflow_summary: workflow.workflow_summary || {},
    success: workflow.success,
    error: workflow.error,
  };
}

function getApiErrorMessage(data: unknown, fallback: string): string {
  if (typeof data === "string" && data.trim()) {
    return data;
  }

  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;

    if (typeof record.error === "string" && record.error.trim()) {
      return record.error;
    }

    if (typeof record.detail === "string" && record.detail.trim()) {
      return record.detail;
    }

    if (record.detail) {
      return JSON.stringify(record.detail);
    }
  }

  return fallback;
}

async function parseApiResponse<T>(
  response: Response,
  fallbackError: string
): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  let data: unknown = null;

  if (isJson) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    throw new Error(getApiErrorMessage(data, fallbackError));
  }

  if (
    data &&
    typeof data === "object" &&
    "success" in data &&
    (data as { success?: boolean }).success === false
  ) {
    throw new Error(getApiErrorMessage(data, fallbackError));
  }

  return data as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
  });

  return parseApiResponse<T>(response, "Failed to fetch data");
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
  });

  return parseApiResponse<T>(response, "Failed to delete data");
}

export async function runAssistant(
  message: string,
  useWeb?: boolean
): Promise<AssistantRunResponse> {
  const response = await fetch(`${API_URL}/assistant/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      use_web: useWeb ?? false,
    }),
  });

  return parseApiResponse<AssistantRunResponse>(
    response,
    "Failed to run AIRA-X assistant"
  );
}

export async function sendChat(
  question: string,
  useWeb?: boolean
): Promise<ChatResponse> {
  const response = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question,
      use_web: useWeb,
    }),
  });

  return parseApiResponse<ChatResponse>(
    response,
    "Failed to send chat message"
  );
}

export async function uploadDocuments(
  files: FileList
): Promise<{ documents: unknown[] }> {
  const body = new FormData();

  Array.from(files).forEach((file) => body.append("files", file));

  const response = await fetch(`${API_URL}/upload`, {
    method: "POST",
    body,
  });

  return parseApiResponse<{ documents: unknown[] }>(
    response,
    "Failed to upload documents"
  );
}

export async function summarizeDocument(
  documentId: number
): Promise<{ summary: string; citations: Citation[] }> {
  const response = await fetch(`${API_URL}/summarize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      document_id: documentId,
    }),
  });

  return parseApiResponse<{ summary: string; citations: Citation[] }>(
    response,
    "Failed to summarize document"
  );
}

export async function runAiraX(goal: string): Promise<AiraXRunResponse> {
  const response = await fetch(`${API_URL}/aira-x/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ goal }),
  });

  return parseApiResponse<AiraXRunResponse>(
    response,
    "Failed to run AIRA-X workflow"
  );
}

export async function approveAiraX(runId: string): Promise<AiraXRunResponse> {
  const response = await fetch(`${API_URL}/aira-x/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ run_id: runId }),
  });

  return parseApiResponse<AiraXRunResponse>(
    response,
    "Failed to approve AIRA-X workflow"
  );
}

export async function rejectAiraX(runId: string): Promise<AiraXRunResponse> {
  const response = await fetch(`${API_URL}/aira-x/reject`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ run_id: runId }),
  });

  return parseApiResponse<AiraXRunResponse>(
    response,
    "Failed to reject AIRA-X workflow"
  );
}

export async function getAiraXTools(): Promise<AiraXToolsResponse> {
  const response = await fetch(`${API_URL}/aira-x/tools`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXToolsResponse>(
    response,
    "Failed to fetch AIRA-X tools"
  );
}

export async function getAiraXAgents(): Promise<AiraXAgentsResponse> {
  const response = await fetch(`${API_URL}/aira-x/agents`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXAgentsResponse>(
    response,
    "Failed to fetch AIRA-X agents"
  );
}

export async function getAiraXAgent(
  agentName: string
): Promise<AiraXAgentResponse> {
  const response = await fetch(`${API_URL}/aira-x/agents/${agentName}`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXAgentResponse>(
    response,
    "Failed to fetch AIRA-X agent"
  );
}

export async function getAiraXRuns(): Promise<AiraXRunsResponse> {
  const response = await fetch(`${API_URL}/aira-x/runs`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXRunsResponse>(
    response,
    "Failed to fetch AIRA-X workflow runs"
  );
}

export async function getAiraXRun(
  runId: string
): Promise<AiraXRunDetailResponse> {
  const response = await fetch(
    `${API_URL}/aira-x/runs/${encodeURIComponent(runId)}`,
    {
      cache: "no-store",
    }
  );

  return parseApiResponse<AiraXRunDetailResponse>(
    response,
    "Failed to fetch AIRA-X workflow run"
  );
}

export async function deleteAiraXRun(
  runId: string
): Promise<AiraXDeleteRunResponse> {
  return apiDelete<AiraXDeleteRunResponse>(
    `/aira-x/runs/${encodeURIComponent(runId)}`
  );
}

export async function deleteSafeAiraXRuns(): Promise<AiraXSafeCleanupResponse> {
  return apiDelete<AiraXSafeCleanupResponse>("/aira-x/runs/maintenance/safe");
}

export async function getAiraXOverview(): Promise<AiraXOverviewResponse> {
  const response = await fetch(`${API_URL}/aira-x/overview`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXOverviewResponse>(
    response,
    "Failed to fetch AIRA-X overview"
  );
}
