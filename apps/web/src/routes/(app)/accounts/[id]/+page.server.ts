import { error, fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import type { Entity } from '#lib/entity.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, params }) => {
	const r = await api(locals, `/accounts/${encodeURIComponent(params.id)}/entity`);
	if (!r.ok) error(r.status, typeof r.body.detail === 'string' ? r.body.detail : 'Could not load account');
	return { entity: r.body as Entity };
};

export const actions: Actions = {
	/** Full name for a stated reason; the API writes every reveal to the audit log. */
	reveal: async ({ locals, params, request }) => {
		const f = await request.formData();
		const r = await api(locals, '/pii/reveal', {
			method: 'POST',
			body: JSON.stringify({ account_id: params.id, reason: f.get('reason') ?? '' })
		});
		if (!r.ok)
			return fail(r.status, {
				message: r.status === 422 ? 'Give a reason (at least 5 characters)' : (r.body.detail ?? 'Not allowed')
			});
		return { revealed: r.body as { name_en: string; name_th: string } };
	}
};
