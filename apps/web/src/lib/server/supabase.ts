import { createServerClient } from '@supabase/ssr';
import type { Cookies } from '@sveltejs/kit';
import { PUBLIC_SUPABASE_ANON_KEY, PUBLIC_SUPABASE_URL } from '$app/env/public';
import { SUPABASE_INTERNAL_URL } from '$app/env/private';

/** Fixed cookie name so the browser (127.0.0.1) and the server (container hostname) agree. */
export const AUTH_COOKIE = 'sb-zentry-auth-token';

export function createSupabase(cookies: Cookies) {
	// Inside Docker the server reaches Supabase by container name; browsers use the public URL.
	const url = SUPABASE_INTERNAL_URL ?? PUBLIC_SUPABASE_URL;
	return createServerClient(url, PUBLIC_SUPABASE_ANON_KEY, {
		cookieOptions: { name: AUTH_COOKIE },
		cookies: {
			getAll: () => cookies.getAll(),
			setAll: (toSet) =>
				toSet.forEach(({ name, value, options }) => cookies.set(name, value, { ...options, path: '/' }))
		}
	});
}
