export type InvolvedAccount = { id: string; role: string; note: string };

export type AgentReport = {
	title?: string;
	summary?: string;
	typology?: string;
	risk_level?: string;
	involved_accounts?: InvolvedAccount[];
	key_transactions?: string[];
	money_trail?: string;
	recommendation?: { action: string; rationale: string };
	mode: 'llm' | 'offline';
	model: string;
	seconds: number;
	tool_calls: { tool: string; args: Record<string, unknown> }[];
	validation: { ok: boolean; cited: string[]; missing_in_db: string[]; not_from_tools: string[] };
};

export type CaseRow = {
	id: string;
	type: string;
	status: string;
	title: string | null;
	risk_level: string | null;
	disposition: string | null;
	ai_summary: string | null;
	str_draft: string | null;
	str_approved_at: string | null;
	agent_report: AgentReport | null;
	investigated_at: string | null;
	created_at: string;
	updated_at: string;
};

export const RISK_TONE: Record<string, string> = {
	critical: 'bg-alert text-white',
	high: 'bg-alert/15 text-alert',
	medium: 'bg-accent/15 text-accent',
	low: 'bg-mist text-ink-muted'
};

export const ACTION_LABEL: Record<string, string> = {
	recommend_freeze: 'Freeze accounts',
	file_str: 'File STR',
	escalate: 'Escalate',
	close: 'Close'
};
