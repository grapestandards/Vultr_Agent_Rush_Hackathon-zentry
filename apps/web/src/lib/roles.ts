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
