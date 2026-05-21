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
  requires_approval: boolean;
  pending_action?: string;
  approval_context?: AiraXApprovalContext;
  approval_context_type?: string;
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
    latest_runs: AiraXWorkflowRun[];
  };
};

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
  const response = await fetch(`${API_URL}/aira-x/runs/${runId}`, {
    cache: "no-store",
  });

  return parseApiResponse<AiraXRunDetailResponse>(
    response,
    "Failed to fetch AIRA-X workflow run"
  );
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