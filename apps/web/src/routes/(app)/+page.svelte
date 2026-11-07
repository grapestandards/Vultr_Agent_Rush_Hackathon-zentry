<script lang="ts">
	import { ROLE_LABEL } from '#lib/roles.ts';
	import { ArrowRightLeft, BellRing, FolderSearch, Receipt, Users, Zap } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const cards = $derived([
		{ key: 'transactions', label: 'Transactions (30 days)', icon: Zap, tone: 'text-accent' },
		{ key: 'accounts', label: 'Accounts monitored', icon: Users, tone: 'text-accent' },
		{ key: 'alerts', label: 'Open alerts', icon: BellRing, tone: 'text-alert' },
		{ key: 'cases', label: 'Cases', icon: FolderSearch, tone: 'text-alert' },
		{ key: 'settlements', label: 'Settlement lines', icon: ArrowRightLeft, tone: 'text-accent' },
		{ key: 'follow_ups', label: 'Follow-ups', icon: Receipt, tone: 'text-accent' }
	] as const);

	const fmt = new Intl.NumberFormat('en-US');
</script>

<section class="mx-auto max-w-5xl pt-6 sm:pt-12">
	<h1 class="text-3xl leading-tight font-semibold tracking-tight sm:text-5xl">
		Hi {data.role ? ROLE_LABEL[data.role] : 'there'},<br />
		<span class="text-ink-muted">ready to follow the money?</span>
	</h1>

	<div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
		{#each cards as card (card.key)}
			{@const value = data.counts[card.key]}
			<article class="rounded-2xl bg-white p-5 shadow-card">
				<card.icon size={22} class={card.tone} />
				<p class="mt-4 text-3xl font-semibold tabular-nums">{value === null ? '—' : fmt.format(value)}</p>
				<p class="mt-1 text-sm text-ink-muted">{card.label}</p>
			</article>
		{/each}
	</div>
	<p class="mt-6 text-xs text-ink-muted">
		Counts respect your role's row-level security — a dash or zero means this role can't see that data.
	</p>
</section>
