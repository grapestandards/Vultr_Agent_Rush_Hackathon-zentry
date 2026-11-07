export type ReconRun = {
	id: string;
	period: string; // "[2026-10-08,2026-11-07)"
	status: 'queued' | 'running' | 'review' | 'done' | 'failed';
	matched_count: number;
	break_count: number;
	stats_json: {
		matched?: number;
		breaks?: number;
		match_rate?: number;
		by_rule?: Record<string, number>;
		by_break?: Record<string, number>;
		ledger_txns?: number;
		settlements?: number;
		auto_closed_follow_ups?: number;
		agent?: 'llm' | 'offline';
	};
	error: string | null;
	created_at: string;
	finished_at: string | null;
};

export type JournalEntry = {
	memo: string;
	lines: { account: string; debit_satang: number; credit_satang: number }[];
};

export type Break = {
	id: number;
	transaction_id: string | null;
	settlement_id: string | null;
	match_rule: string | null;
	break_type: BreakType;
	diff_satang: number | null;
	explanation: string | null;
	journal_json: JournalEntry | null;
	follow_up_json: { counterparty: string; amount_satang: number; title: string } | null;
	resolution: 'confirmed' | 'dismissed' | 'auto_cleared' | null;
	resolved_at: string | null;
	note: string | null;
};

export type BreakType = 'timing' | 'fee' | 'amount_mismatch' | 'duplicate' | 'missing_in_bank' | 'missing_in_ledger';

export const BREAK_LABEL: Record<BreakType, string> = {
	timing: 'Timing',
	fee: 'Fee',
	amount_mismatch: 'Amount mismatch',
	duplicate: 'Duplicate',
	missing_in_bank: 'Missing in bank',
	missing_in_ledger: 'Missing in ledger'
};

export const RULE_LABEL: Record<string, string> = {
	ref_exact: 'Reference',
	amount_time_fuzzy: 'Amount + date + name',
	many_to_one: 'Many-to-one batch'
};

/** "[2026-10-08,2026-11-07)" → "08 Oct – 06 Nov" (upper bound is exclusive). */
export function periodLabel(period: string) {
	const [lo, hi] = period.replace(/[[\]()]/g, '').split(',');
	const end = new Date(`${hi}T00:00:00Z`);
	end.setUTCDate(end.getUTCDate() - 1);
	const f = (d: Date) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' });
	return `${f(new Date(`${lo}T00:00:00Z`))} – ${f(end)}`;
}

export type FollowUp = {
	id: string;
	case_id: string | null;
	kind: 'recon' | 'victim_refund' | 'chargeback';
	title: string;
	counterparty: string;
	contact: string | null;
	amount_due_satang: number;
	due_date: string | null;
	stage: Stage;
	promise_date: string | null;
	next_action_at: string | null;
	level: number;
	source_ref: string | null;
	closed_reason: string | null;
	created_at: string;
	updated_at: string;
};

export type Stage = 'new' | 'reminded' | 'promised' | 'escalated' | 'closed';

export type Message = {
	id: string;
	follow_up_id: string;
	channel: string;
	direction: 'out' | 'in';
	status: 'draft' | 'approved' | 'sent' | 'rejected' | 'received';
	level: number | null;
	subject: string | null;
	draft: string;
	author: string | null;
	sent_at: string | null;
	created_at: string;
};

export const STAGES: { stage: Stage; label: string }[] = [
	{ stage: 'new', label: 'New' },
	{ stage: 'reminded', label: 'Reminded' },
	{ stage: 'promised', label: 'Promised' },
	{ stage: 'escalated', label: 'Escalated' },
	{ stage: 'closed', label: 'Closed' }
];

export const KIND_LABEL: Record<FollowUp['kind'], string> = {
	recon: 'Recon balance',
	victim_refund: 'Victim refund',
	chargeback: 'Chargeback'
};
