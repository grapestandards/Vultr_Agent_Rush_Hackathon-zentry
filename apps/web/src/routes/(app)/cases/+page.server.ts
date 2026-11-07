import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals }) => {
	const { data } = await locals.supabase
		.from('cases')
		.select('id, title, status, risk_level, disposition, updated_at, case_links(alert_id, account_id)')
		.order('updated_at', { ascending: false })
		.limit(100);
	return { cases: data ?? [] };
};
