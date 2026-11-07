export type GraphNode = {
	id: string;
	type: 'wallet' | 'bank' | 'merchant';
	status: string;
	name: string; // masked for people ("Somying Sd****"), full for merchants
	name_th: string;
	kyc_level: number;
	risk: number | null;
	cases: string[];
	in_satang: number;
	out_satang: number;
};

export type GraphTxn = {
	id: string;
	from_account: string;
	to_account: string;
	amount_satang: number;
	ts: string;
	traced_satang?: number;
};

export type NetworkGroup = { id: string; members: string[]; flagged: number; case_id: string | null };

export type Network = {
	window: { start: string; end: string };
	seeds: string[];
	nodes: GraphNode[];
	transactions: GraphTxn[];
	groups: NetworkGroup[];
};

export type VictimCandidate = { account_id: string; name: string; paid_satang: number; payments: number; first_ts: string };

export type Trace = {
	victim: string;
	paid_satang: number;
	first_ts: string;
	held_satang: number;
	cashed_out_satang: number;
	elsewhere_satang: number;
	held: { account_id: string; satang: number }[];
	cash_out: { account_id: string; satang: number }[];
	path: GraphTxn[];
	nodes: GraphNode[];
	candidates: VictimCandidate[];
};
