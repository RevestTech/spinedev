/**
 * User-facing pipeline copy — written for business stakeholders and engineers.
 * Business: outcome, accountability, next step. Technical: role names, artifacts, gates.
 */

export const PIPELINE_COPY = {
  attention: {
    decisions: (n: number) =>
      n === 1 ? '1 approval pending' : `${n} approvals pending`,
    decisionsReview: (n: number) =>
      n === 1 ? '1 approval to review' : `${n} approvals to review`,
    paused: 'Pipeline paused — action required',
  },
  status: {
    idle: 'Pipeline ready',
    working: (role: string) => `${role} in progress`,
    starting: (step: string) => `Starting ${step}`,
    decisions: (n: number) =>
      n === 1 ? '1 approval required to continue' : `${n} approvals required to continue`,
    pausedPrefix: 'Pipeline paused',
    failed: (role: string) => `${role} did not complete successfully`,
  },
  subtext: {
    roleProgress: (detail: string, elapsedSec: number, typical: string) =>
      `${detail} · ${elapsedSec}s elapsed · typical ${typical}`,
    decisions:
      'Review each item in Decisions and approve or reject. Approved items advance the delivery pipeline.',
    suggestedAction: (label: string) =>
      `Recommended next step: ${label}. You may choose a different action from the controls below.`,
    dispatchProgress: (firstStep: string, elapsedSec: number, typical: string) =>
      `${firstStep} · ${elapsedSec}s elapsed · typical ${typical}`,
    dispatchWaiting:
      'The selected step is running. A new approval will appear in Decisions when it completes.',
    background:
      'Automated roles run in the background. Progress appears in the activity log below.',
    decisionsUnblock: 'Your approval unblocks the next automated step.',
  },
  terminal: {
    titleIdle: 'Activity log',
    titleLive: (role: string) => `${role} · activity log`,
    statusRunning: 'In progress',
    emptyRunning: 'Step in progress — log output will appear here shortly.',
    emptyIdle:
      'No active step. Start a pipeline action from the controls on the left, or wait for the next approval gate.',
    refreshNote: 'Updates every few seconds while a step is running',
  },
  fixLoop: {
    exhausted: (iteration: number, max: number) =>
      `Security review remains blocked after ${iteration} automated remediation ${iteration === 1 ? 'attempt' : 'attempts'} (maximum ${max} automatic retries). Click **Resume pipeline** — Spine will scan for findings, patch targeted files, and re-run security automatically.`,
    iteration: (current: number, max: number) =>
      `Remediation attempt ${current} of ${max}. Workflow: approve security findings → engineer updates code → approve code output → security review runs again. If an approval is already waiting, use Decisions instead of starting another run.`,
  },
  pipelineTab: {
    badgeActionRequired: 'Action required',
    controlsLead:
      'Manual pipeline controls. Use these when a step failed, timed out, or you need to override the default sequence.',
    noActions: 'No manual controls are available for the current phase.',
    suggested: 'Recommended',
    runAction: (label: string) => `Run ${label}`,
    starting: 'Starting…',
    activityTitle: (label: string) => `${label} in progress`,
    activityWhenDone: 'When this step completes:',
    sending: 'Submitting request…',
    roleRunning: 'Step in progress',
    hubActive: 'Processing on Hub',
    notePlaceholder: 'Optional note for the audit trail',
    liveTerminalLabel: 'Activity log',
    refreshHint: 'Auto-scroll · updates every few seconds while a step runs',
    decisionsEmptyLead: 'The delivery pipeline is paused. Open the',
    decisionsEmptyTrail: 'tab to review recommended next steps.',
  },
  dispatch: {
    queued: (label: string) => `${label} has been queued and is starting now.`,
    terminalQueued: (label: string) => `[system] ${label} queued`,
  },
  decisions: {
    hintBriefing: 'Acknowledge to dismiss this briefing.',
    hintApproval: 'Approve to advance this project to the next delivery gate.',
    hintDefault: 'Approve or reject to continue.',
    reviewButton: (n: number) =>
      n === 1 ? 'Review 1 approval' : `Review ${n} approvals`,
  },
  reasons: {
    fix_loop_exhausted:
      'Security still failing after automatic fix attempts — resume runs targeted remediation',
    code_review_blocked:
      'Security review flagged issues — approve the findings in Decisions or start remediation',
    no_pending_decisions:
      'No automated step is running and no approvals are waiting',
    last_role_failed: 'The previous automated step failed',
    workspace_empty_stale_metadata:
      'Project workspace is empty — regenerate code before continuing',
    workspace_empty_no_code: 'No generated code yet — run the engineer step',
    pending_decisions: 'Approvals waiting in your queue',
    dispatch_stale: 'Previous step timed out — safe to retry',
    role_failure: 'Previous automated step failed',
  },
  dispatchKinds: {
    code_review_blocked: 'Security remediation',
    sprint_plan_approval: 'Code generation',
    code_approval: 'Security review',
    code_review_pass: 'Environment setup',
    devops_approval: 'Quality assurance',
    prd_approval: 'Roadmap planning',
    roadmap_approval: 'Architecture design',
    trd_approval: 'Sprint planning',
  },
  recoveryActions: {
    retry_engineer_remediate: {
      role: 'engineer',
      label: 'Apply security remediation',
      typical: '1–3 min',
      steps: [
        'Security findings are sent to the engineer role with full project context',
        'Updated source files are written to the project workspace',
        'After you approve the new code, security review runs again',
        'An approval card is created in Decisions when the step completes',
      ],
      outcome:
        'Approve the updated code in Decisions. Do not start remediation again while an approval is already pending.',
    },
    retry_engineer: {
      role: 'engineer',
      label: 'Regenerate application code',
      typical: '1–3 min',
      steps: [
        'The engineer role reads the approved sprint plan',
        'Application files are generated in the project workspace',
        'Security review is scheduled after code approval',
      ],
      outcome: 'An approval card will appear in Decisions when code generation completes.',
    },
    retry_code_review: {
      role: 'security_engineer',
      label: 'Run security review',
      typical: '45–120 sec',
      steps: [
        'The security engineer scans the workspace against OWASP and NIST controls',
        'Findings are recorded in the code review artifact',
        'The pipeline advances or returns to remediation based on severity',
      ],
      outcome:
        'If critical or high findings remain, start security remediation with the updated report.',
    },
    retry_devops: {
      role: 'devops',
      label: 'Run environment setup',
      typical: '30–90 sec',
      steps: [
        'Install and smoke-test commands run in the project workspace',
        'Results are saved to the project record',
      ],
      outcome: 'Quality assurance can proceed after a successful install.',
    },
    retry_qa: {
      role: 'qa',
      label: 'Generate test plan',
      typical: '30–60 sec',
      steps: [
        'The QA role produces a test plan from the TRD and current workspace',
      ],
      outcome: 'Review the test plan artifact before advancing to release.',
    },
    resume: {
      role: 'engineer',
      label: 'Resume pipeline',
      typical: '1–3 min',
      steps: [
        'The Hub selects the most appropriate next step for the current phase',
        'That role runs with current project context and artifacts',
      ],
      outcome: 'Watch the activity log for the role that started.',
    },
  },
  roles: {
    product: {
      label: 'Product',
      what: 'Drafting the product requirements document from intake',
      typical: '~30–60s',
    },
    planner: {
      label: 'Planner',
      what: 'Building the delivery roadmap and milestone plan',
      typical: '~30–60s',
    },
    architect: {
      label: 'Architect',
      what: 'Producing the technical design and stack decisions',
      typical: '~45–90s',
    },
    conductor: {
      label: 'Conductor',
      what: 'Breaking work into sprint tasks and assignments',
      typical: '~30–60s',
    },
    engineer: {
      label: 'Engineer',
      what: 'Generating and updating application source code',
      typical: '~60–180s',
    },
    security_engineer: {
      label: 'Security review',
      what: 'Evaluating code against security and compliance controls',
      typical: '~45–120s',
    },
    devops: {
      label: 'DevOps',
      what: 'Installing dependencies and validating the workspace',
      typical: '~30–90s',
    },
    qa: {
      label: 'QA',
      what: 'Authoring the test plan and coverage matrix',
      typical: '~30–60s',
    },
    release_manager: {
      label: 'Release manager',
      what: 'Preparing release criteria and deployment options',
      typical: '~30–60s',
    },
    devops_release: {
      label: 'Local deployment',
      what: 'Starting the application on a local preview port',
      typical: '~10–20s',
    },
  },
  phase: {
    intake: 'Intake',
    plan: 'Planning',
    build: 'Build',
    verify: 'Verify',
    release: 'Release',
  },
} as const;

export function humanStuckReason(reason: string): string {
  const labels = PIPELINE_COPY.reasons as Record<string, string>;
  return labels[reason] ?? reason.replace(/_/g, ' ');
}

export function dispatchKindLabel(kind: string | undefined): string {
  if (!kind) return 'pipeline step';
  const labels = PIPELINE_COPY.dispatchKinds as Record<string, string>;
  return labels[kind] ?? kind.replace(/_/g, ' ');
}

export function formatPhaseLabel(phase: string | undefined): string {
  if (!phase) return 'Unknown';
  const p = phase.toLowerCase();
  if (p === 'intake') return PIPELINE_COPY.phase.intake;
  if (p.startsWith('plan')) return PIPELINE_COPY.phase.plan;
  if (p.startsWith('build')) return PIPELINE_COPY.phase.build;
  if (p.startsWith('verify') || p === 'acceptance') return PIPELINE_COPY.phase.verify;
  if (p === 'released' || p === 'release' || p === 'operate') return PIPELINE_COPY.phase.release;
  if (p === 'retro') return 'Retrospective';
  if (p === 'terminated') return 'Terminated';
  return phase.replace(/_/g, ' ');
}

export function formatProjectSubtitle(
  projectType: string,
  phase: string,
  status: string
): string {
  const type = projectType.charAt(0).toUpperCase() + projectType.slice(1);
  const phaseLabel = formatPhaseLabel(phase);
  const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
  return `${type} · ${phaseLabel} · ${statusLabel}`;
}

export type RecoveryActionKey = keyof typeof PIPELINE_COPY.recoveryActions;

export function recoveryActionInfo(action: string) {
  const key = action as RecoveryActionKey;
  return PIPELINE_COPY.recoveryActions[key] ?? null;
}
