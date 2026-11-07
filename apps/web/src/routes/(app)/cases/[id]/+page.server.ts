import { error, fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import type { CaseRow } from '#lib/cases.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, params }) => {
	const sb = locals.supabase;
	const { data: kase } = await sb.from('cases').select('*').eq('id', params.id).single();
	if (!kase) error(404, 'Case not found');

	const [{ data: links }, { data: proposals }] = await Promise.all([
		sb
			.from('case_links')
			.select('account_id, alerts(id, account_id, transaction_id, score, reason, rule_hits, txn_ts)')
			.eq('case_id', params.id),
		sb.from('case_proposals').select('*').eq('case_id', params.id).order('created_at')
	]);
	const alerts = (links ?? []).flatMap((l) => (l.alerts ? [l.alerts] : [])) as unknown as {
		id: string;
		account_id: string;
		transaction_id: string;
		score: number;
		reason: string;
		rule_hits: string[];
		txn_ts: string;
	}[];
	const report = (kase as CaseRow).agent_report;
	const accountIds = [
		...new Set([
			...alerts.map((a) => a.account_id),
			...(report?.involved_accounts ?? []).map((a) => a.id)
		])
	];
	const alerted = [...new Set(alerts.map((a) => a.account_id))];
	const [{ data: accounts }, { data: timeline }] = await Promise.all([
		sb.from('accounts').select('id, type, status, opened_at, customers(name_en:display_en)').in('id', accountIds),
		alerted.length
			? sb
					.from('transactions')
					.select('id, from_account, to_account, amount_satang, channel, ts')
					.or(`from_account.in.(${alerted.join(',')}),to_account.in.(${alerted.join(',')})`)
					.order('ts', { ascending: false })
					.limit(40)
			: Promise.resolve({ data: [] })
	]);
	return {
		kase: kase as CaseRow,
		alerts: alerts.sort((a, b) => b.score - a.score),
		proposals: proposals ?? [],
		// many-to-one embed: PostgREST returns an object, not the array supabase-js infers
		accounts: (accounts ?? []) as unknown as {
			id: string;
			type: string;
			status: string;
			opened_at: string;
			customers: { name_en: string } | null;
		}[],
		timeline: timeline ?? [],
		alerted
	};
};

export const actions: Actions = {
	investigate: async ({ locals, params }) => {
		const r = await api(locals, `/cases/${params.id}/investigate`, { method: 'POST' });
		if (!r.ok) return fail(r.status, { message: r.body.detail ?? 'Could not start investigation' });
		return { message: 'Investigation queued — the summary updates when it finishes.' };
	},
	decide: async ({ locals, params, request }) => {
		const form = await request.formData();
		const r = await api(locals, `/cases/${params.id}/decision`, {
			method: 'POST',
			body: JSON.stringify({
				decision: form.get('decision'),
				note: form.get('note') ?? '',
				str_text: form.get('str_text') ?? undefined,
				approve_str: form.get('approve_str') === 'on'
			})
		});
		if (!r.ok) return fail(r.status, { message: r.body.detail ?? 'Decision failed' });
		return { message: `Recorded: ${String(form.get('decision')).replaceAll('_', ' ')}` };
	}
};
