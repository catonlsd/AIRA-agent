// How a finalized streamed turn chooses its card.
//
// A turn renders as the WorkflowResultCard ONLY when it's a real run / a run that
// needs workflow-level approval (e.g. a git preflight). A turn that is merely
// *awaiting approval of a plan* — a code plan, a runtime-validation gate, an
// artifact plan, or a clarification — belongs in the answer card, which carries
// the right approval controls. Routing those into the workflow card hides the
// Approve button and makes a "plan_ready" status look like a failure.
//
// Pure + unit-tested so the routing can't silently regress.

export type FinalLike = {
  mode?: unknown;
  status?: unknown;
  requires_approval?: unknown;
  meta?: Record<string, unknown> | null;
};

/** True when the finalized turn should render as a workflow result card. */
export function isWorkflowResult(final: FinalLike): boolean {
  const mode = String(final?.mode ?? "");
  const status = String(final?.status ?? "");
  const meta = (final?.meta ?? {}) as Record<string, unknown>;

  // Plan / clarification / artifact turns awaiting approval are answer-card turns.
  const isAwaitingPlan =
    status === "plan_ready" ||
    status === "awaiting_action_approval" ||
    mode === "clarification" ||
    Boolean(meta.artifact_pending);
  if (isAwaitingPlan) return false;

  // A genuine execution run, or a workflow-level approval gate (git preflight).
  return (
    mode === "execution" ||
    mode === "research_then_execution" ||
    final?.requires_approval === true ||
    status === "requires_approval"
  );
}
