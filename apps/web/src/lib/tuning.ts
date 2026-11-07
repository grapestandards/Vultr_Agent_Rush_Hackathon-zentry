export type CurvePoint = {
	threshold: number;
	precision: number;
	recall: number;
	alerts_per_day: number;
	mules_caught: number;
	clean_accounts_flagged: number;
};

export type Evaluation = {
	pr_auc: number;
	precision_at_100: number;
	recall: number;
	alerts_per_day: number;
	mules_caught: number;
	curve: CurvePoint[];
};

export type ModelCard = {
	features?: string[];
	params?: Record<string, number | string>;
	holdout?: { seed: number; rows: number; fraud_rows: number };
	training?: { history_seed: number; rows: number; fraud_rows: number; analyst_labels: boolean };
	curve?: CurvePoint[];
	champion?: (Evaluation & { id: string; name: string }) | null;
	gained_accounts?: string[];
	lost_accounts?: string[];
	seconds?: number;
};

export type ModelVersion = {
	id: string;
	name: string | null;
	stage: 'challenger' | 'shadow' | 'champion' | 'retired';
	metrics_json: Partial<Evaluation> & Record<string, unknown>;
	params_json: Record<string, unknown>;
	card_json: ModelCard;
	shadow_json: { rows: number; would_alert: number; champion_alerts: number; both: number; updated_at: string } | null;
	created_at: string;
	promoted_at: string | null;
};

export type TrainRun = {
	id: string;
	status: 'queued' | 'provisioning' | 'running' | 'succeeded' | 'failed' | 'cancelled';
	runner: 'local' | 'vultr';
	params_json: Record<string, unknown>;
	vultr_instance_id: string | null;
	model_version_id: string | null;
	log_tail: string | null;
	error: string | null;
	created_at: string;
	started_at: string | null;
	finished_at: string | null;
};

/** Feature groups for the toggle chips; names match zt_core.features.FEATURES. */
export const FEATURE_GROUPS: [string, string[]][] = [
	['Transaction', ['side_out', 'amount_log', 'hour']],
	['Account', ['age_days', 'kyc_level']],
	['Velocity', ['in_cnt_1h', 'in_amt_1h', 'in_cnt_24h', 'in_amt_24h', 'out_cnt_1h', 'out_amt_1h', 'out_cnt_24h', 'out_amt_24h', 'out_in_ratio_24h']],
	['Counterparties', ['senders_24h', 'new_senders_24h', 'receivers_24h']],
	['Behaviour', ['dwell_min', 'quiet_days', 'device_accounts']],
	['Graph', ['g_degree', 'g_pagerank', 'g_community_size']]
];

export const RUN_TONE: Record<TrainRun['status'], string> = {
	queued: 'bg-mist text-ink-muted',
	provisioning: 'bg-accent/15 text-accent',
	running: 'bg-accent text-white',
	succeeded: 'bg-ink text-white',
	failed: 'bg-alert text-white',
	cancelled: 'bg-mist text-ink-muted'
};
