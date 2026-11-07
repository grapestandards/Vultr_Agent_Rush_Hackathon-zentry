import { fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import type { FollowUp, Message } from '#lib/recon.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, depends }) => {
	depends('app:follow-ups');
	const sb = locals.supabase;
	const [{ data: open }, { data: closed }] = await Promise.all([
		sb.from('follow_ups').select('*').neq('stage', 'closed').order('updated_at', { ascending: false }).limit(200),
		sb.from('follow_ups').select('*').eq('stage', 'closed').order('updated_at', { ascending: false }).limit(20)
	]);
	const items = [...(open ?? []), ...(closed ?? [])] as FollowUp[];
	const { data: messages } = items.length
		? await sb.from('messages').select('*').in('follow_up_id', items.map((f) => f.id)).order('created_at')
		: { data: [] };
	return { items, messages: (messages ?? []) as Message[] };
};

const detail = (body: { detail?: unknown }, fallback: string) =>
	typeof body.detail === 'string' ? body.detail : fallback;

export const actions: Actions = {
	approve: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/messages/${f.get('id')}/approve`, {
			method: 'POST',
			body: JSON.stringify({ subject: f.get('subject') || null, body: f.get('body') || null })
		});
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not approve') });
		return { message: 'Approved and sent to the demo inbox (nothing leaves Zentry).' };
	},
	reject: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/messages/${f.get('id')}/reject`, { method: 'POST' });
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not reject') });
		return { message: 'Draft rejected.' };
	},
	run: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/followups/${f.get('id')}/run`, { method: 'POST' });
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not run the agent') });
		return { message: 'The follow-up agent is drafting the next message…' };
	},
	reply: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/followups/${f.get('id')}/reply`, {
			method: 'POST',
			body: JSON.stringify({ text: f.get('text') })
		});
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not record the reply') });
		return { message: 'Reply recorded — the agent is reading it for a payment date.' };
	},
	close: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/followups/${f.get('id')}/close`, {
			method: 'POST',
			body: JSON.stringify({ reason: f.get('reason'), note: f.get('note') ?? '' })
		});
		if (!r.ok) return fail(r.status, { message: detail(r.body, 'Could not close') });
		return { message: 'Follow-up closed.' };
	}
};
