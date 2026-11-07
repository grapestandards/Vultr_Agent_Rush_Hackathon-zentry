<script lang="ts">
	import { RISK_TONE } from '#lib/cases.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<section class="mx-auto max-w-5xl pt-4">
	<h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">
		{data.cases.filter((c) => c.status !== 'closed').length} open cases
		<span class="text-ink-muted">· {data.cases.length} total</span>
	</h1>
	<ul class="mt-6 space-y-3">
		{#each data.cases as c (c.id)}
			{@const accounts = c.case_links.filter((l) => l.account_id).length}
			{@const alerts = c.case_links.filter((l) => l.alert_id).length}
			<li>
				<a href="/cases/{c.id}" class="flex items-center gap-4 rounded-2xl bg-white p-4 shadow-card transition hover:ring-2 hover:ring-accent/30 sm:p-5">
					<span class="rounded-full px-2.5 py-1 text-xs font-semibold capitalize {RISK_TONE[c.risk_level ?? 'low']}">
						{c.risk_level ?? 'new'}
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate font-semibold">{c.title}</p>
						<p class="text-xs text-ink-muted">{accounts} accounts · {alerts} alerts · {c.status}{c.disposition ? ` · ${c.disposition}` : ''}</p>
					</div>
				</a>
			</li>
		{:else}
			<li class="rounded-2xl bg-white p-10 text-center text-ink-muted shadow-card">No cases yet.</li>
		{/each}
	</ul>
</section>
