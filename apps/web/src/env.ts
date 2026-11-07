import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	PUBLIC_SUPABASE_URL: { public: true, description: 'Supabase URL as seen from the browser' },
	PUBLIC_SUPABASE_ANON_KEY: { public: true, description: 'Supabase anon key (access is enforced by RLS)' },
	API_INTERNAL_URL: {
		schema: (value) => value || 'http://127.0.0.1:8000',
		description: 'Zentry API base URL as seen from the SvelteKit server'
	},
	SUPABASE_INTERNAL_URL: {
		schema: (value) => value || undefined,
		description: 'Supabase URL as seen from the server, when it differs (e.g. inside Docker)'
	}
});
