import { fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import type { Break, ReconRun } from '#lib/recon.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, url, depends }) => {
	depends('app:recon');
	const sb = locals.supabase;
	const { data: runs } = await sb.from('recon_runs').select('*').order('created_at', { ascending: false }).limit(6);
	const run = ((runs ?? []) as ReconRun[]).find((r) => r.id === url.searchParams.get('run')) ?? (runs?.[0] as ReconRun | undefined);
	let breaks: Break[] = [];
	if (run) {
		const { data } = await sb
			.from('recon_matches')
			.select('id, transaction_id, settlement_id, match_rule, break_type, diff_satang, explanation, journal_json, follow_up_json, resolution, resolved_at, note')
			.eq('run_id', run.id)
			.not('break_type', 'is', null)
			.order('break_type')
			.order('id');
		breaks = (data ?? []) as Break[];
	}
	return { runs: (runs ?? []) as ReconRun[], run: run ?? null, breaks };
};

const detail = (body: { detail?: unknown }, fallback: string) =>
	typeof body.detail === 'string' ? body.detail : fallback;

export const actions: Actions = {
	run: async ({ locals }) => {
		const r = await api(locals, '/recon/runs', { method: 'POST', body: '{}' });
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not start reconciliation') });
		return { message: 'Reconciliation queued — matching the ledger against the settlement files.' };
	},
	upload: async ({ locals, request }) => {
		const f = await request.formData();
		const file = f.get('file');
		if (!(file instanceof File) || !file.size) return fail(400, { message: 'Choose a CSV file' });
		if (file.size > 5_000_000) return fail(413, { message: 'Files up to 5 MB' });
		const r = await api(locals, '/recon/upload', {
			method: 'POST',
			body: JSON.stringify({ source: f.get('source'), filename: file.name, content: await file.text(), run: true })
		});
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Upload failed') });
		return { message: `${r.body.rows} rows loaded from ${file.name}; reconciliation queued.` };
	},
	resolve: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/recon/breaks/${f.get('id')}/resolve`, {
			method: 'POST',
			body: JSON.stringify({ action: f.get('action'), note: f.get('note') ?? '' })
		});
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not update the break') });
		return {
			message:
				f.get('action') === 'confirm'
					? r.body.follow_up_id
						? 'Journal entry confirmed — a payment follow-up was opened.'
						: 'Journal entry confirmed.'
					: 'Break dismissed.'
		};
	}
};
