<script lang="ts">
	import { onMount } from 'svelte';
	import { enhance } from '$app/forms';
	import { invalidateAll } from '$app/navigation';
	import { ACTION_LABEL, RISK_TONE } from '#lib/cases.ts';
	import { RULE_SHORT } from '#lib/alerts.ts';
	import { browserSupabase } from '#lib/supabase.ts';
	import { BadgeCheck, Bot, Network, ShieldAlert, Snowflake, Sparkles, TriangleAlert } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();

	const k = $derived(data.kase);
	const report = $derived(k.agent_report);
	const accountById = $derived(new Map(data.accounts.map((a) => [a.id, a])));
	const pending = $derived(data.proposals.filter((p) => p.status === 'pending'));
	let investigating = $state(false);
	let strText = $state('');
	$effect.pre(() => {
		strText = k.str_draft ?? '';
	});

	onMount(() => {
		const supabase = browserSupabase();
		let channel: ReturnType<typeof supabase.channel> | undefined;
		supabase.auth.getSession().then(({ data: { session } }) => {
			if (session) supabase.realtime.setAuth(session.access_token);
			channel = supabase
				.channel(`case-${k.id}`)
				.on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'cases', filter: `id=eq.${k.id}` }, () => {
					investigating = false;
					invalidateAll();
				})
				.subscribe();
		});
		return () => channel && supabase.removeChannel(channel);
	});

	const thb = (satang: number) => `฿${(satang / 100).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	const when = (ts: string | null) =>
		ts
			? new Date(ts).toLocaleString('en-GB', { timeZone: 'Asia/Bangkok', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
			: '—';
	const roleOf = (id: string) => report?.involved_accounts?.find((a) => a.id === id)?.role;
</script>

<section class="mx-auto max-w-6xl pt-4">
	<a href="/cases" class="text-xs text-ink-muted hover:text-ink">← Cases</a>
	<div class="mt-2 flex flex-wrap items-start justify-between gap-4">
		<h1 class="max-w-3xl text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
			{k.title ?? 'Case'}
			<span class="block text-base font-normal text-ink-muted">{k.status}{k.disposition ? ` · ${k.disposition}` : ''} · updated {when(k.updated_at)}</span>
		</h1>
		{#if k.risk_level}
			<span class="rounded-full px-3 py-1.5 text-sm font-semibold capitalize {RISK_TONE[k.risk_level]}">{k.risk_level} risk</span>
		{/if}
	</div>

	{#if form?.message}
		<p class="mt-4 rounded-2xl bg-white px-4 py-3 text-sm shadow-card">{form.message}</p>
	{/if}

	<div class="mt-6 grid gap-4 lg:grid-cols-3">
		<!-- AI summary -->
		<article class="rounded-2xl bg-white p-5 shadow-card lg:col-span-2">
			<div class="flex flex-wrap items-center gap-2">
				<span class="grid size-8 place-items-center rounded-full bg-ink text-white"><Bot size={16} /></span>
				<h2 class="font-semibold">AI investigation</h2>
				{#if report}
					{#if report.validation.ok}
						<span class="flex items-center gap-1 rounded-full bg-accent/15 px-2.5 py-1 text-[11px] font-medium text-accent">
							<BadgeCheck size={12} /> {report.validation.cited.length} ids verified
						</span>
					{:else}
						<span class="flex items-center gap-1 rounded-full bg-alert/15 px-2.5 py-1 text-[11px] font-medium text-alert">
							<TriangleAlert size={12} /> rejected by validator
						</span>
					{/if}
					<span class="ml-auto text-[11px] text-ink-muted">
						{report.mode === 'llm' ? report.model : 'offline planner'} · {report.tool_calls.length} tool calls · {report.seconds}s
					</span>
				{/if}
			</div>
			{#if k.ai_summary}
				<p class="mt-4 leading-relaxed">{k.ai_summary}</p>
				{#if report?.money_trail}
					<p class="mt-3 rounded-xl bg-mist px-3 py-2 font-mono text-xs text-ink-muted">{report.money_trail}</p>
				{/if}
				{#if report?.key_transactions?.length}
					<div class="mt-3 flex flex-wrap gap-1.5">
						{#each report.key_transactions as t (t)}
							<span class="rounded-full bg-mist px-2.5 py-1 font-mono text-[11px] text-ink-muted">{t}</span>
						{/each}
					</div>
				{/if}
			{:else if report && !report.validation.ok}
				<p class="mt-4 text-sm text-alert">
					The last AI report cited ids that could not be verified ({[...report.validation.missing_in_db, ...report.validation.not_from_tools].join(', ')}), so it is hidden. Re-run the investigation.
				</p>
			{:else}
				<p class="mt-4 text-sm text-ink-muted">Not investigated yet.</p>
			{/if}
		</article>

		<!-- Proposals -->
		<article class="rounded-2xl bg-white p-5 shadow-card">
			<h2 class="flex items-center gap-2 font-semibold"><Sparkles size={16} class="text-accent" /> Agent proposals</h2>
			<p class="mt-1 text-xs text-ink-muted">The agent can only propose. You decide.</p>
			<ul class="mt-4 space-y-3">
				{#each data.proposals as p (p.id)}
					<li class="rounded-xl bg-mist p-3 text-sm {p.status !== 'pending' ? 'opacity-60' : ''}">
						<p class="font-medium">{ACTION_LABEL[p.action] ?? p.action} <span class="text-xs text-ink-muted">· {p.status}</span></p>
						<p class="mt-1 text-xs text-ink-muted">{p.rationale}</p>
					</li>
				{:else}
					<li class="text-sm text-ink-muted">None.</li>
				{/each}
			</ul>
		</article>
	</div>

	<div class="mt-4 grid gap-4 lg:grid-cols-3">
		<!-- Accounts -->
		<article class="rounded-2xl bg-white p-5 shadow-card lg:col-span-2">
			<div class="flex items-center justify-between">
				<h2 class="font-semibold">Accounts</h2>
				{#if data.alerted[0]}
					<a href="/graph?account={data.alerted[0]}&case={k.id}" class="flex items-center gap-1 text-xs font-medium text-accent hover:underline">
						<Network size={14} /> Open in Graph Explorer
					</a>
				{/if}
			</div>
			<div class="mt-3 overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="text-left text-xs text-ink-muted">
						<tr><th class="py-2 pr-3 font-medium">Account</th><th class="pr-3 font-medium">Holder</th><th class="pr-3 font-medium">Role</th><th class="pr-3 font-medium">Opened</th><th class="font-medium">Status</th></tr>
					</thead>
					<tbody>
						{#each [...data.alerted, ...(report?.involved_accounts ?? []).map((a) => a.id).filter((id) => !data.alerted.includes(id))] as id (id)}
							{@const a = accountById.get(id)}
							<tr class="border-t border-black/5">
								<td class="py-2 pr-3 font-mono text-xs">{id}</td>
								<td class="pr-3">{a?.customers?.name_en ?? ''}</td>
								<td class="pr-3 capitalize">{roleOf(id) ?? (data.alerted.includes(id) ? 'flagged' : '')}</td>
								<td class="pr-3 text-xs text-ink-muted">{a ? new Date(a.opened_at).toLocaleDateString('en-GB') : ''}</td>
								<td>
									{#if a?.status === 'frozen'}
										<span class="flex items-center gap-1 text-xs font-medium text-accent"><Snowflake size={12} /> frozen</span>
									{:else}
										<span class="text-xs text-ink-muted">{a?.status}</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</article>

		<!-- Alerts -->
		<article class="rounded-2xl bg-white p-5 shadow-card">
			<h2 class="font-semibold">Alerts · {data.alerts.length}</h2>
			<ul class="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
				{#each data.alerts as a (a.id)}
					<li class="rounded-xl bg-mist p-3 text-xs">
						<p class="flex justify-between font-medium"><span class="font-mono">{a.account_id}</span><span class="text-alert">{a.score}</span></p>
						<p class="mt-1 text-ink-muted">{a.reason}</p>
						{#if a.rule_hits.length}<p class="mt-1 text-ink">{a.rule_hits.map((r) => RULE_SHORT[r] ?? r).join(' · ')}</p>{/if}
					</li>
				{/each}
			</ul>
		</article>
	</div>

	<!-- Timeline -->
	<article class="mt-4 rounded-2xl bg-white p-5 shadow-card">
		<h2 class="font-semibold">Recent transfers of flagged accounts</h2>
		<div class="mt-3 overflow-x-auto">
			<table class="w-full text-sm">
				<thead class="text-left text-xs text-ink-muted"><tr><th class="py-2 pr-3 font-medium">When</th><th class="pr-3 font-medium">Txn</th><th class="pr-3 font-medium">From</th><th class="pr-3 font-medium">To</th><th class="pr-3 text-right font-medium">Amount</th></tr></thead>
				<tbody>
					{#each data.timeline as t (t.id)}
						<tr class="border-t border-black/5">
							<td class="py-1.5 pr-3 text-xs text-ink-muted">{when(t.ts)}</td>
							<td class="pr-3 font-mono text-xs">{t.id}</td>
							<td class="pr-3 font-mono text-xs {data.alerted.includes(t.from_account) ? 'text-alert' : ''}">{t.from_account}</td>
							<td class="pr-3 font-mono text-xs {data.alerted.includes(t.to_account) ? 'text-alert' : ''}">{t.to_account}</td>
							<td class="pr-3 text-right tabular-nums">{thb(t.amount_satang)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</article>

	<!-- Decision + STR -->
	<form method="POST" action="?/decide" use:enhance class="mt-4 rounded-2xl bg-white p-5 shadow-card">
		<h2 class="flex items-center gap-2 font-semibold"><ShieldAlert size={16} class="text-alert" /> Decision & STR</h2>
		<label class="mt-3 block text-xs text-ink-muted" for="str">STR draft (edit before approving)</label>
		<textarea id="str" name="str_text" bind:value={strText} rows="10" class="mt-1 w-full rounded-xl border-0 bg-mist p-3 font-mono text-xs ring-1 ring-black/5 outline-none focus:ring-2 focus:ring-accent"></textarea>
		<div class="mt-3 flex flex-wrap items-center gap-3">
			<label class="flex items-center gap-2 text-sm"><input type="checkbox" name="approve_str" class="accent-ink" /> Approve STR</label>
			{#if k.str_approved_at}<span class="text-xs text-accent">STR approved {when(k.str_approved_at)}</span>{/if}
			<input name="note" placeholder="Note (optional)" class="min-w-48 flex-1 rounded-full bg-mist px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-accent" />
		</div>
		<div class="mt-4 flex flex-wrap gap-2">
			<button name="decision" value="freeze" class="flex items-center gap-1.5 rounded-full bg-alert px-4 py-2 text-sm font-semibold text-white hover:bg-alert/90"><Snowflake size={14} /> Freeze flagged accounts</button>
			<button name="decision" value="close_fraud" class="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-ink/85">Close · confirmed fraud</button>
			<button name="decision" value="escalate" class="rounded-full bg-white px-4 py-2 text-sm font-semibold ring-1 ring-black/10 hover:ring-black/20">Escalate</button>
			<button name="decision" value="close_false_positive" class="rounded-full bg-white px-4 py-2 text-sm font-semibold text-ink-muted ring-1 ring-black/10 hover:ring-black/20">Close · false positive</button>
		</div>
	</form>

	<!-- AI bar -->
	<div class="sticky bottom-4 mt-6 rounded-3xl bg-white/90 p-3 shadow-panel backdrop-blur">
		<div class="flex flex-wrap items-center gap-2">
			<span class="pl-2 text-xs text-ink-muted"><Sparkles size={12} class="inline text-accent" /> Zentry AI</span>
			<form method="POST" action="?/investigate" use:enhance={() => { investigating = true; return async ({ update }) => update({ reset: false }); }}>
				<button disabled={investigating} class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">
					{investigating ? 'Investigating…' : k.investigated_at ? 'Re-run investigation' : 'Investigate'}
				</button>
			</form>
			{#if data.alerted[0]}
				<a href="/graph?account={data.alerted[0]}&case={k.id}&trace=1" class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white">Trace from victim</a>
			{/if}
			<a href="#str" class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white">Draft STR</a>
		</div>
	</div>
</section>
