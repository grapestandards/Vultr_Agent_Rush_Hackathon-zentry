import type { Session, SupabaseClient, User } from '@supabase/supabase-js';

export type Role = 'analyst' | 'finance_ops' | 'collections' | 'compliance_manager' | 'admin';

declare global {
	namespace App {
		interface Locals {
			supabase: SupabaseClient;
			/** Validated session: the JWT is checked against Supabase Auth, not just decoded. */
			safeGetSession: () => Promise<{ session: Session | null; user: User | null }>;
		}
	}
}

export {};
