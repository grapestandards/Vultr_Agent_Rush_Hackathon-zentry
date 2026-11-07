<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onMount } from 'svelte';
	import { browserSupabase } from '#lib/supabase.ts';
	import { thb } from '#lib/money.ts';
	import { BREAK_LABEL, RULE_LABEL, periodLabel, type Break, type BreakType } from '#lib/recon.ts';
	import { ArrowRightLeft, Check, FileUp, Play, Sparkles, X } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();

	const canAct = $derived(['finance_ops', 'compliance_manager', 'admin'].includes(data.role ?? ''));
	const run = $derived(data.run);
	const stats = $derived(run?.stats_json ?? {});
	const busy = $derived(data.runs.some((r) => r.status === 'queued' || r.status === 'running'));
	const open = $derived(data.breaks.filter((b) => !b.resolution).length);

	let filter = $state<BreakType | 'all'>('all');
	const shown = $derived(filter === 'all' ? data.breaks : data.breaks.filter((b) => b.break_type === filter));
	let picked = $state<number | null>(null);
	const sel = $derived(shown.find((b) => b.id === picked) ?? shown.find((b) => !b.resolution) ?? shown[0]);

	onMount(() => {
		const supabase = browserSupabase();
		let channel: ReturnType<typeof supabase.channel> | undefined;
		supabase.auth.getSession().then(({ data: { session } }) => {
			if (session) supabase.realtime.setAuth(session.access_token);
			channel = supabase
				.channel('recon')
				.on('postgres_changes', { event: '*', schema: 'public', table: 'recon_runs' }, () => invalidate('app:recon'))
				.subscribe();
		});
		return () => channel && supabase.removeChannel(channel);
	});

	const tone: Record<BreakType, string> = {
		timing: 'bg-mist text-ink-muted',
		fee: 'bg-alert/10 text-alert',
		amount_mismatch: 'bg-alert/10 text-alert',
		duplicate: 'bg-accent/15 text-accent',
		missing_in_bank: 'bg-alert/10 text-alert',
		missing_in_ledger: 'bg-accent/15 text-accent'
	};
	const baht = (s: number) => (s ? `฿${(s / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}` : '');
	const signed = (v: number | null) => (v === null ? '—' : v === 0 ? '฿0.00' : `${v > 0 ? '+' : '−'}${baht(Math.abs(v))}`);
	const ref = (b: Break) => b.settlement_id ?? b.transaction_id ?? '';
</script>

<section class="mx-auto max-w-6xl pt-4">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">Reconciliation</h1>
			<p class="mt-1 text-sm text-ink-muted">
				Ledger × gateway settlement file × bank statement{#if run} · {periodLabel(run.period)}{/if}
			</p>
		</div>
		{#if canAct}
			<div class="flex flex-wrap items-center gap-2">
				<form method="POST" action="?/upload" enctype="multipart/form-data" use:enhance class="flex items-center gap-2 rounded-full bg-white py-1 pr-1 pl-3 shadow-card">
					<FileUp size={14} class="text-accent" />
					<select name="source" class="bg-transparent text-xs" aria-label="File source">
						<option value="bank">Bank statement</option>
						<option value="gateway">Gateway settlement</option>
					</select>
					<input name="file" type="file" accept=".csv,text/csv" class="w-44 text-xs file:mr-2 file:rounded-full file:border-0 file:bg-mist file:px-2 file:py-1 file:text-xs" />
					<button disabled={busy} class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">Upload</button>
				</form>
				<form method="POST" action="?/run" use:enhance>
					<button disabled={busy} class="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-xs font-medium text-white disabled:opacity-40">
						<Play size={13} /> {busy ? 'Matching…' : 'Run reconciliation'}
					</button>
				</form>
			</div>
		{/if}
	</div>

	{#if form?.message}
		<p class="mt-4 rounded-2xl bg-ink px-4 py-2.5 text-sm text-white">{form.message}</p>
	{/if}

	{#if !run}
		<div class="mt-8 rounded-3xl bg-white p-10 text-center shadow-card">
			<ArrowRightLeft class="mx-auto text-accent" />
			<p class="mt-3 font-medium">No reconciliation yet</p>
			<p class="mt-1 text-sm text-ink-muted">Run one over the ledger period, or upload a settlement / bank statement CSV.</p>
		</div>
	{:else}
		<!-- KPIs -->
		<div class="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
			<div class="rounded-3xl bg-white p-4 shadow-card">
				<p class="text-xs text-ink-muted">Auto-match rate</p>
				<p class="mt-1 text-2xl font-semibold">{stats.match_rate !== undefined ? `${(stats.match_rate * 100).toFixed(2)}%` : '—'}</p>
				<p class="text-[11px] text-ink-muted">{(stats.ledger_txns ?? 0).toLocaleString()} ledger txns · {(stats.settlements ?? 0).toLocaleString()} settlement rows</p>
			</div>
			<div class="rounded-3xl bg-white p-4 shadow-card">
				<p class="text-xs text-ink-muted">Matched</p>
				<p class="mt-1 text-2xl font-semibold">{run.matched_count.toLocaleString()}</p>
				<p class="text-[11px] text-ink-muted">
					{#each Object.entries(stats.by_rule ?? {}) as [rule, n], i (rule)}{i ? ' · ' : ''}{RULE_LABEL[rule] ?? rule} {n.toLocaleString()}{/each}
				</p>
			</div>
			<div class="rounded-3xl bg-white p-4 shadow-card">
				<p class="text-xs text-ink-muted">Breaks</p>
				<p class="mt-1 text-2xl font-semibold text-alert">{run.break_count}</p>
				<p class="text-[11px] text-ink-muted">{open} waiting for review</p>
			</div>
			<div class="rounded-3xl bg-white p-4 shadow-card">
				<p class="text-xs text-ink-muted">Run</p>
				<p class="mt-1 text-2xl font-semibold capitalize">{run.status}</p>
				<p class="flex items-center gap-1 text-[11px] text-ink-muted"><Sparkles size={11} /> agent: {stats.agent ?? '—'}{#if stats.auto_closed_follow_ups} · {stats.auto_closed_follow_ups} follow-ups auto-closed{/if}</p>
			</div>
		</div>
		{#if run.error}<p class="mt-3 rounded-2xl bg-alert/10 px-4 py-2 text-sm text-alert">{run.error}</p>{/if}

		<!-- filter chips -->
		<div class="mt-5 flex flex-wrap gap-1.5">
			<button onclick={() => (filter = 'all')} class="rounded-full px-3 py-1 text-xs {filter === 'all' ? 'bg-ink text-white' : 'bg-white text-ink-muted shadow-card'}">All {data.breaks.length}</button>
			{#each Object.entries(stats.by_break ?? {}) as [type, n] (type)}
				<button onclick={() => (filter = type as BreakType)} class="rounded-full px-3 py-1 text-xs {filter === type ? 'bg-ink text-white' : 'bg-white text-ink-muted shadow-card'}">
					{BREAK_LABEL[type as BreakType] ?? type} {n}
				</button>
			{/each}
		</div>

		<div class="mt-3 grid gap-4 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
			<div class="max-h-[560px] overflow-auto rounded-3xl bg-white shadow-card">
				<table class="w-full text-left text-xs">
					<thead class="sticky top-0 bg-white text-ink-muted">
						<tr><th class="px-4 py-3 font-medium">Break</th><th class="font-medium">Reference</th><th class="text-right font-medium">Difference</th><th class="px-4 text-right font-medium">Status</th></tr>
					</thead>
					<tbody>
						{#each shown as b (b.id)}
							<tr onclick={() => (picked = b.id)} class="cursor-pointer border-t border-mist {sel?.id === b.id ? 'bg-mist/70' : 'hover:bg-mist/40'}">
								<td class="px-4 py-2.5"><span class="rounded-full px-2 py-0.5 text-[11px] {tone[b.break_type]}">{BREAK_LABEL[b.break_type]}</span></td>
								<td class="font-mono text-[11px]">{ref(b)}</td>
								<td class="text-right tabular-nums">{signed(b.diff_satang)}</td>
								<td class="px-4 text-right">
									{#if b.resolution}<span class="text-ink-muted capitalize">{b.resolution}</span>{:else}<span class="text-alert">open</span>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			{#if sel}
				<div class="space-y-4 rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between gap-2">
						<span class="rounded-full px-2.5 py-1 text-xs {tone[sel.break_type]}">{BREAK_LABEL[sel.break_type]}</span>
						<span class="text-[11px] text-ink-muted">{sel.match_rule ? `matched by ${RULE_LABEL[sel.match_rule]}` : 'no counterpart found'}</span>
					</div>
					<div class="flex flex-wrap gap-1.5 font-mono text-[11px]">
						{#if sel.transaction_id}<span class="rounded-full bg-mist px-2 py-0.5">ledger {sel.transaction_id}</span>{/if}
						{#if sel.settlement_id}<span class="rounded-full bg-mist px-2 py-0.5">settlement {sel.settlement_id}</span>{/if}
					</div>
					<div>
						<p class="flex items-center gap-1.5 text-xs font-medium text-ink-muted"><Sparkles size={12} class="text-accent" /> Recon agent</p>
						<p class="mt-1 text-sm leading-relaxed">{sel.explanation}</p>
					</div>
					{#if sel.journal_json}
						<div>
							<p class="text-xs font-medium text-ink-muted">Drafted journal entry</p>
							<p class="mt-1 text-xs">{sel.journal_json.memo}</p>
							<table class="mt-2 w-full text-xs">
								<thead class="text-ink-muted"><tr><th class="text-left font-medium">Account</th><th class="text-right font-medium">Debit</th><th class="text-right font-medium">Credit</th></tr></thead>
								<tbody class="tabular-nums">
									{#each sel.journal_json.lines as l, i (i)}
										<tr class="border-t border-mist"><td class="py-1.5 {l.credit_satang ? 'pl-4' : ''}">{l.account}</td><td class="text-right">{baht(l.debit_satang)}</td><td class="text-right">{baht(l.credit_satang)}</td></tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
					{#if sel.follow_up_json}
						<p class="rounded-2xl bg-mist px-3 py-2 text-xs">Confirming opens a follow-up: <span class="font-medium">{sel.follow_up_json.title}</span> · {thb(sel.follow_up_json.amount_satang)} from {sel.follow_up_json.counterparty}</p>
					{/if}
					{#if sel.resolution}
						<p class="text-xs text-ink-muted">{sel.resolution} {sel.resolved_at ? new Date(sel.resolved_at).toLocaleString('en-GB', { timeZone: 'Asia/Bangkok' }) : ''}{sel.note ? ` — ${sel.note}` : ''}</p>
					{:else if canAct}
						<form method="POST" action="?/resolve" use:enhance class="space-y-2">
							<input type="hidden" name="id" value={sel.id} />
							<input name="note" placeholder="Note (optional)" class="w-full rounded-xl bg-mist px-3 py-2 text-xs" />
							<div class="flex gap-2">
								<button name="action" value="confirm" class="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-ink py-2 text-xs font-medium text-white"><Check size={13} /> Confirm entry</button>
								<button name="action" value="dismiss" class="flex items-center gap-1.5 rounded-full bg-mist px-4 py-2 text-xs font-medium"><X size={13} /> Dismiss</button>
							</div>
						</form>
					{/if}
				</div>
			{/if}
		</div>

		{#if data.runs.length > 1}
			<div class="mt-5 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
				Earlier runs:
				{#each data.runs as r (r.id)}
					<a href="?run={r.id}" class="rounded-full px-3 py-1 {r.id === run.id ? 'bg-ink text-white' : 'bg-white shadow-card'}">
						{new Date(r.created_at).toLocaleString('en-GB', { timeZone: 'Asia/Bangkok', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })} · {r.break_count} breaks
					</a>
				{/each}
			</div>
		{/if}
	{/if}
</section>
