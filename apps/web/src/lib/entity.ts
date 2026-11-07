export type Entity = {
	profile: {
		id: string;
		type: 'wallet' | 'bank' | 'merchant';
		status: string;
		bank_code: string | null;
		opened_at: string;
		name: string; // masked unless merchant
		name_th: string;
		kyc_level: number;
		customer_since: string;
		accounts_held: number;
		devices: number;
		labels: string[];
		alerts: number;
		max_score: number | null;
	};
	stats: { in_satang: number; out_satang: number; transfers: number; counterparties: number; first_seen: string | null; last_seen: string | null };
	cases: { id: string; status: string; disposition: string | null; risk_level: string | null; title: string | null }[];
	history: { day: string; in_satang: number; out_satang: number; balance_satang: number }[];
	counterparties: { account_id: string; name: string | null; type: string | null; risk: number | null; in_satang: number; out_satang: number; count: number }[];
	transfers: {
		id: string;
		ts: string;
		direction: 'in' | 'out';
		counterparty: string;
		counterparty_name: string | null;
		counterparty_risk: number | null;
		amount_satang: number;
		channel: string;
		device_id: string | null;
	}[];
};
