import { API_INTERNAL_URL } from '$app/env/private';

/** Call the Zentry API as the signed-in user (their Supabase JWT is verified by the API). */
export async function api(locals: App.Locals, path: string, init: RequestInit = {}) {
	const {
		data: { session }
	} = await locals.supabase.auth.getSession();
	const res = await fetch(`${API_INTERNAL_URL}${path}`, {
		...init,
		headers: {
			'content-type': 'application/json',
			authorization: `Bearer ${session?.access_token ?? ''}`,
			...init.headers
		}
	});
	const body = await res.json().catch(() => ({}));
	return { ok: res.ok, status: res.status, body };
}
