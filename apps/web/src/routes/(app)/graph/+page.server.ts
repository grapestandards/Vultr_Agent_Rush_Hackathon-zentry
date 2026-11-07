import { api } from '#lib/server/api.ts';
import type { Network, Trace } from '#lib/graph.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, url }) => {
	const caseId = url.searchParams.get('case');
	const account = url.searchParams.get('account');
	if (!caseId && !account) {
		const { data: cases } = await locals.supabase
			.from('cases')
			.select('id, title, risk_level, status')
			.neq('status', 'closed')
			.order('created_at', { ascending: false });
		return { network: null, trace: null, cases: cases ?? [], error: null };
	}
	const q = new URLSearchParams();
	if (caseId) q.set('case', caseId);
	else if (account) q.append('accounts', account);
	const tq = new URLSearchParams(caseId ? { case: caseId } : { account: account! });
	const victim = url.searchParams.get('victim');
	if (victim) tq.set('victim', victim);
	const wantTrace = url.searchParams.get('trace') === '1' || !!victim;
	const [net, trace] = await Promise.all([
		api(locals, `/graph/network?${q}`),
		wantTrace ? api(locals, `/graph/trace?${tq}`) : Promise.resolve(null)
	]);
	return {
		network: net.ok ? (net.body as Network) : null,
		trace: trace?.ok ? (trace.body as Trace) : null,
		cases: [],
		error: net.ok ? (trace && !trace.ok ? trace.body.detail : null) : (net.body.detail ?? 'Could not load graph')
	};
};
