import type { PageServerLoad } from './$types';

// Tables the Command Center summarises. RLS decides what each role can count.
const TABLES = ['transactions', 'accounts', 'alerts', 'cases', 'settlements', 'follow_ups'] as const;

export const load: PageServerLoad = async ({ locals }) => {
	const counts = await Promise.all(
		TABLES.map(async (table) => {
			const { count, error } = await locals.supabase.from(table).select('id', { count: 'exact', head: true });
			return [table, error ? null : (count ?? 0)] as const;
		})
	);
	return { counts: Object.fromEntries(counts) as Record<(typeof TABLES)[number], number | null> };
};
