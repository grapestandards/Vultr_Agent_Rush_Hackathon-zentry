import { redirect } from '@sveltejs/kit';
import type { Handle } from '@sveltejs/kit/hooks';
import { createSupabase } from '#lib/server/supabase.ts';
import { canOpen, roleOf, sectionOf } from '#lib/roles.ts';

const PUBLIC_PATHS = ['/login', '/welcome'];

export const handle: Handle = async ({ event, resolve }) => {
	event.locals.supabase = createSupabase(event.cookies);
	event.locals.safeGetSession = async () => {
		const {
			data: { session }
		} = await event.locals.supabase.auth.getSession();
		if (!session) return { session: null, user: null };
		// getSession() only decodes the cookie; getUser() verifies it with Supabase Auth.
		const {
			data: { user },
			error
		} = await event.locals.supabase.auth.getUser();
		return error ? { session: null, user: null } : { session, user };
	};

	if (!PUBLIC_PATHS.includes(event.url.pathname)) {
		const { user } = await event.locals.safeGetSession();
		if (!user) redirect(303, event.url.pathname === '/' ? '/welcome' : '/login');
		// a role outside a section lands on the section page, which explains who it is for (detail
		// pages would 404 instead, since RLS hides their rows)
		const section = sectionOf(event.url.pathname);
		if (section && event.url.pathname !== section && !canOpen(roleOf(user), event.url.pathname)) redirect(303, section);
	}

	return resolve(event, {
		filterSerializedResponseHeaders: (name) => name === 'content-range' || name === 'x-supabase-api-version'
	});
};
