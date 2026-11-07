export type TopFeature = { feature: string; value: number; contribution: number };

export type AlertRow = {
	id: string;
	transaction_id: string | null;
	account_id: string;
	score: number;
	priority: number;
	reason: string | null;
	rule_hits: string[];
	top_features_json: TopFeature[];
	status: 'new' | 'in_case' | 'closed';
	txn_ts: string | null;
	created_at: string;
	accounts: { type: string; customers: { name_en: string; name_th: string } | null } | null;
	case_links: { case_id: string }[];
};

export const ALERT_SELECT =
	'id, transaction_id, account_id, score, priority, reason, rule_hits, top_features_json, status, txn_ts, created_at, accounts(type, customers(name_en, name_th)), case_links(case_id)';

export const RULE_SHORT: Record<string, string> = {
	pass_through: 'Pass-through',
	fan_in_out: 'Fan-in/out',
	dormant_reactivation: 'Dormant',
	structuring: 'Structuring',
	new_account_strangers: 'New + strangers'
};
