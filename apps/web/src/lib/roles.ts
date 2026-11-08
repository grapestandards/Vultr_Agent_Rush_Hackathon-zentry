import type { Role } from '../app.d.ts';

export const ROLE_LABEL: Record<Role, string> = {
	analyst: 'AML / Fraud Analyst',
	finance_ops: 'Finance Ops',
	collections: 'Collections Officer',
	compliance_manager: 'Compliance Manager',
	admin: 'Admin'
};

export const DEMO_ROLES: Role[] = ['analyst', 'finance_ops', 'collections', 'compliance_manager'];

export const demoEmail = (role: Role) => `${role}@demo.zentry.local`;

export function roleOf(user: { app_metadata?: Record<string, unknown> } | null): Role | null {
	const role = user?.app_metadata?.role;
	return typeof role === 'string' && role in ROLE_LABEL ? (role as Role) : null;
}

/** Who can use each section, mirroring the API's require() and the RLS policies. Admin passes everywhere. */
export const SECTION_ROLES: Record<string, Role[]> = {
	'/alerts': ['analyst', 'compliance_manager'],
	'/cases': ['analyst', 'compliance_manager'],
	'/graph': ['analyst', 'compliance_manager'],
	'/recon': ['finance_ops', 'compliance_manager'],
	'/follow-ups': ['collections', 'finance_ops', 'compliance_manager'],
	'/tuning': ['analyst', 'compliance_manager']
};

/** The restricted section `path` belongs to, e.g. '/cases' for '/cases/123'. */
export function sectionOf(path: string): string | undefined {
	return Object.keys(SECTION_ROLES).find((k) => path === k || path.startsWith(`${k}/`));
}

/** Roles allowed on `path`, or null when every role may open it. */
export function sectionRoles(path: string): Role[] | null {
	const key = sectionOf(path);
	return key ? SECTION_ROLES[key] : null;
}

export function canOpen(role: Role | null, path: string): boolean {
	const roles = sectionRoles(path);
	return !roles || role === 'admin' || (role !== null && roles.includes(role));
}
