import { json } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import type { RequestHandler } from './$types';

/** Browser → API proxy for hop expansion and re-tracing (`kind` = network | trace). */
export const GET: RequestHandler = async ({ locals, url }) => {
	const q = new URLSearchParams(url.searchParams);
	const kind = q.get('kind') === 'trace' ? 'trace' : 'network';
	q.delete('kind');
	const r = await api(locals, `/graph/${kind}?${q}`);
	return json(r.body, { status: r.status });
};
