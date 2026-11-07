import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter(),
			// The monorepo keeps a single .env at the repo root.
			env: { dir: '../..' },
			// Canonical origin for CSRF checks. adapter-node assumes https unless a proxy sends
			// PROTOCOL_HEADER, so plain-http local Docker builds pass ORIGIN at build time.
			paths: { origin: process.env.ORIGIN || undefined }
		})
	]
});
