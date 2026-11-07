import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { PUBLIC_SUPABASE_ANON_KEY, PUBLIC_SUPABASE_URL } from '$app/env/public';

/** Fixed cookie name so the browser (127.0.0.1) and the server (container hostname) agree. */
export const AUTH_COOKIE = 'sb-zentry-auth-token';

let client: SupabaseClient | undefined;

/** Browser-side client (session from the auth cookie). Used for Realtime subscriptions. */
export function browserSupabase(): SupabaseClient {
	client ??= createBrowserClient(PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_ANON_KEY, {
		cookieOptions: { name: AUTH_COOKIE }
	});
	return client;
}
