<script lang="ts">
	import { onMount } from 'svelte';
	import { ALERT_SELECT, RULE_SHORT, type AlertRow } from '#lib/alerts.ts';
	import { browserSupabase } from '#lib/supabase.ts';
	import { Radio } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let live = $state<AlertRow[]>([]);
	let fresh = $state(new Set<string>());
	let connected = $state(false);
	let filter = $state<number | null>(null);

	const alerts = $derived(
		[...live, ...data.alerts.filter((a) => !live.some((l) => l.id === a.id))].filter(
			(a) => filter === null || a.priority === filter
		)
	);
	const counts = $derived(
		[1, 2, 3].map((p) => [...live, ...data.alerts].filter((a) => a.priority === p).length)
	);

	onMount(() => {
		const supabase = browserSupabase();
		let channel: ReturnType<typeof supabase.channel> | undefined;
		supabase.auth.getSession().then(({ data: { session } }) => {
			if (session) supabase.realtime.setAuth(session.access_token);
			channel = supabase
				.channel('alert-queue')
				.on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'alerts' }, async (payload) => {
					const { data: row } = await supabase
						.from('alerts')
						.select(ALERT_SELECT)
						.eq('id', payload.new.id)
						.single();
					if (!row) return;
					const alert = row as unknown as AlertRow;
					live = [alert, ...live];
					fresh = new Set([...fresh, alert.id]);
					setTimeout(() => {
						fresh.delete(alert.id);
						fresh = new Set(fresh);
					}, 4000);
				})
				.subscribe((status) => (connected = status === 'SUBSCRIBED'));
		});
		return () => channel && supabase.removeChannel(channel);
	});

	const fmtTime = (ts: string | null) =>
		ts
			? new Date(ts).toLocaleString('en-GB', {
					timeZone: 'Asia/Bangkok',
					day: '2-digit',
					month: 'short',
					hour: '2-digit',
					minute: '2-digit'
				})
			: '';
	const tone = (score: number) =>
		score >= 90 ? 'bg-alert text-white' : score >= 80 ? 'bg-alert/15 text-alert' : 'bg-accent/15 text-accent';
</script>

<section class="mx-auto max-w-5xl pt-4">
	<div class="flex flex-wrap items-end justify-between gap-4">
		<h1 class="text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
			{alerts.length} alerts <span class="text-ink-muted">waiting for review</span>
		</h1>
		<span class="flex items-center gap-1.5 text-xs font-medium {connected ? 'text-accent' : 'text-ink-muted'}">
			<Radio size={14} class={connected ? 'animate-pulse' : ''} />
			{connected ? 'Live' : 'Connecting…'}
		</span>
	</div>

	<div class="mt-6 flex flex-wrap gap-2">
		{#each [null, 1, 2, 3] as p (p)}
			<button
				onclick={() => (filter = p)}
				class="rounded-full px-3 py-1.5 text-xs font-medium transition
					{filter === p ? 'bg-ink text-white' : 'bg-white text-ink-muted shadow-card hover:text-ink'}"
			>
				{p === null ? 'All' : `P${p} · ${counts[p - 1]}`}
			</button>
		{/each}
	</div>

	{#if data.error}
		<p class="mt-6 text-sm text-alert">{data.error}</p>
	{:else if alerts.length === 0}
		<div class="mt-10 rounded-2xl bg-white p-10 text-center text-ink-muted shadow-card">
			No open alerts. New ones appear here as transactions stream in.
		</div>
	{:else}
		<ul class="mt-6 space-y-3">
			{#each alerts as a (a.id)}
				<li
					class="rounded-2xl bg-white p-4 shadow-card transition-colors duration-1000 sm:p-5
						{fresh.has(a.id) ? 'ring-2 ring-alert/60 bg-alert/5' : ''}"
				>
					<div class="flex items-start gap-4">
						<div class="grid size-12 shrink-0 place-items-center rounded-2xl text-base font-semibold tabular-nums {tone(a.score)}">
							{a.score}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
								<p class="font-semibold">{a.accounts?.customers?.name_en ?? a.account_id}</p>
								<p class="font-mono text-xs text-ink-muted">{a.account_id} · {a.accounts?.type}</p>
								<p class="ml-auto text-xs text-ink-muted">P{a.priority} · {fmtTime(a.txn_ts)}</p>
							</div>
							<p class="mt-1 text-sm text-ink-muted">{a.reason}</p>
							{#if a.rule_hits.length}
								<div class="mt-2 flex flex-wrap gap-1.5">
									{#each a.rule_hits as r (r)}
										<span class="rounded-full bg-ink px-2.5 py-1 text-[11px] font-medium text-white">{RULE_SHORT[r] ?? r}</span>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>
