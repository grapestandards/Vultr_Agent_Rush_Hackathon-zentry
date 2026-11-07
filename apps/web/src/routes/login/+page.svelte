<script lang="ts">
	import { enhance } from '$app/forms';
	import { DEMO_ROLES, ROLE_LABEL, demoEmail } from '#lib/roles.ts';
	import { ShieldCheck } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { form }: PageProps = $props();
	let email = $state('');
	$effect.pre(() => {
		if (form?.email) email = form.email;
	});
	let busy = $state(false);
</script>

<main class="grid min-h-screen place-items-center p-4">
	<div class="glass w-full max-w-md rounded-3xl p-8 shadow-panel sm:p-10">
		<div class="mb-8 flex items-center gap-2 text-sm font-semibold">
			<span class="grid size-8 place-items-center rounded-full bg-ink text-white"><ShieldCheck size={16} /></span>
			Zentry
		</div>
		<h1 class="text-3xl leading-tight font-semibold tracking-tight">
			Welcome back,<br /><span class="text-ink-muted">follow the money.</span>
		</h1>

		<form
			method="POST"
			class="mt-8 space-y-3"
			use:enhance={() => {
				busy = true;
				return async ({ update }) => {
					await update();
					busy = false;
				};
			}}
		>
			<input
				name="email"
				type="email"
				required
				placeholder="Email"
				bind:value={email}
				class="w-full rounded-2xl border-0 bg-white px-4 py-3 shadow-card ring-1 ring-black/5 outline-none focus:ring-2 focus:ring-accent"
			/>
			<input
				name="password"
				type="password"
				required
				placeholder="Password"
				class="w-full rounded-2xl border-0 bg-white px-4 py-3 shadow-card ring-1 ring-black/5 outline-none focus:ring-2 focus:ring-accent"
			/>
			{#if form?.message}
				<p class="text-sm text-alert" role="alert">{form.message}</p>
			{/if}
			<button
				disabled={busy}
				class="w-full rounded-full bg-ink px-4 py-3 text-sm font-semibold text-white transition hover:bg-ink/85 disabled:opacity-60"
			>
				{busy ? 'Signing in…' : 'Sign in'}
			</button>
		</form>

		<div class="mt-8">
			<p class="mb-2 text-xs font-medium text-ink-muted">Demo accounts</p>
			<div class="flex flex-wrap gap-2">
				{#each DEMO_ROLES as role (role)}
					<button
						type="button"
						onclick={() => (email = demoEmail(role))}
						class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white/90 transition hover:bg-ink/80"
					>
						{ROLE_LABEL[role]}
					</button>
				{/each}
			</div>
		</div>
	</div>
</main>
