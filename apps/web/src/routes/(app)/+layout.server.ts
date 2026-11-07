import { roleOf } from '#lib/roles.ts';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
	const { user } = await locals.safeGetSession();
	return { email: user?.email ?? '', role: roleOf(user) };
};
