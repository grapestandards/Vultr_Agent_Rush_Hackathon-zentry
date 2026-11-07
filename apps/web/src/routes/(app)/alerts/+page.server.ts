import { ALERT_SELECT, type AlertRow } from '#lib/alerts.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals }) => {
	const { data, error } = await locals.supabase
		.from('alerts')
		.select(ALERT_SELECT)
		.eq('status', 'new')
		.order('priority')
		.order('score', { ascending: false })
		.order('created_at', { ascending: false })
		.limit(200);
	return { alerts: (data ?? []) as unknown as AlertRow[], error: error?.message ?? null };
};
