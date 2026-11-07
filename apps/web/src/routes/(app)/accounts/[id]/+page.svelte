<script lang="ts">
	import { enhance } from '$app/forms';
	import { thb } from '#lib/money.ts';
	import { ArrowDownLeft, ArrowUpRight, Eye, EyeOff, Network, ShieldAlert, Store, User, Wallet } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();

	const e = $derived(data.entity);
	const p = $derived(e.profile);
	const canReveal = $derived(['analyst', 'compliance_manager', 'collections', 'admin'].includes(data.role ?? ''));
	let asking = $state(false);
	let tab = $state<'counterparties' | 'transfers' | 'cases'>('counterparties');
	let chart = $state<'balance' | 'flow'>('balance');
	const masked = $derived(p.type !== 'merchant');

	// balance / flow chart
	const W = 560, H = 190, PX = 8, PY = 14;
	const series = $derived(e.history);
	const vals = $derived(chart === 'balance' ? series.map((h) => h.balance_satang) : series.flatMap((h) => [h.in_satang, -h.out_satang]));
	const lo = $derived(Math.min(0, ...vals));
	const hi = $derived(Math.max(1, ...vals));
	const sx = (i: number) => PX + (i / Math.max(1, series.length - 1)) * (W - 2 * PX);
	const sy = (v: number) => H - PY - ((v - lo) / (hi - lo || 1)) * (H - 2 * PY);
	const line = $derived(series.map((h, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(h.balance_satang).toFixed(1)}`).join(' '));
	const area = $derived(series.length ? `${line} L${sx(series.length - 1)},${sy(lo)} L${sx(0)},${sy(lo)} Z` : '');
	const barW = $derived(Math.max(2, (W - 2 * PX) / Math.max(1, series.length) - 3));
	let hover = $state<number | null>(null);

	const date = (d: string | null) =>
		d ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Bangkok' }) : '—';
	const when = (d: string) =>
		new Date(d).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Bangkok' });
	const riskDot = (r: number | null) => ((r ?? 0) >= 90 ? 'bg-alert' : (r ?? 0) >= 70 ? 'bg-[#f4a46a]' : 'bg-haze');
	const labelTone = (l: string) =>
		l.startsWith('risk') || l === 'confirmed fraud' ? 'bg-alert/10 text-alert' : l === 'frozen' ? 'bg-accent text-white' : l.startsWith('rule') ? 'bg-ink text-white' : 'bg-mist text-ink-muted';
</script>

<section class="mx-auto flex max-w-6xl flex-col pt-4 lg:h-full">
	<!-- header -->
	<div class="flex flex-wrap items-start gap-5">
		<div class="grid size-20 shrink-0 place-items-center rounded-full text-white shadow-card {p.type === 'merchant' ? 'bg-ink' : (p.max_score ?? 0) >= 70 ? 'bg-alert' : 'bg-accent'}">
			{#if p.type === 'merchant'}<Store size={34} />{:else if p.type === 'bank'}<Wallet size={34} />{:else}<User size={34} />{/if}
		</div>
		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-center gap-2">
				<h1 class="text-3xl font-semibold tracking-tight">{form?.revealed ? form.revealed.name_en : p.name}</h1>
				{#if masked}
					<span class="flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium {form?.revealed ? 'bg-alert/10 text-alert' : 'bg-mist text-ink-muted'}">
						{#if form?.revealed}<Eye size={12} /> revealed · audited{:else}<EyeOff size={12} /> PII masked{/if}
					</span>
				{/if}
				<span class="rounded-full bg-white px-2.5 py-1 font-mono text-[11px] shadow-card">{p.id}</span>
			</div>
			<p class="mt-0.5 text-sm text-ink-muted">{form?.revealed ? form.revealed.name_th : p.name_th}</p>
			<div class="mt-2 flex flex-wrap gap-1.5">
				{#each p.labels as l (l)}<span class="rounded-full px-2.5 py-1 text-[11px] font-medium capitalize {labelTone(l)}">{l}</span>{/each}
				<span class="rounded-full bg-mist px-2.5 py-1 text-[11px] text-ink-muted">KYC {p.kyc_level}</span>
				{#if p.bank_code}<span class="rounded-full bg-mist px-2.5 py-1 text-[11px] text-ink-muted">bank {p.bank_code}</span>{/if}
			</div>
		</div>
		<div class="flex flex-col items-end gap-2">
			<div class="flex gap-2">
				{#if masked && canReveal && !form?.revealed}
					<button onclick={() => (asking = !asking)} class="flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-xs font-medium shadow-card"><Eye size={13} /> Reveal name</button>
				{/if}
				<a href="/graph?account={p.id}" class="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-xs font-medium text-white"><Network size={13} /> Visualize</a>
			</div>
			{#if asking && !form?.revealed}
				<form method="POST" action="?/reveal" use:enhance class="flex w-80 gap-2 rounded-2xl bg-white p-2 shadow-card">
					<input name="reason" required minlength="5" placeholder="Reason, e.g. STR filing for case …" class="min-w-0 flex-1 rounded-xl bg-mist px-3 py-1.5 text-xs" />
					<button class="rounded-full bg-ink px-3 text-xs font-medium text-white">Reveal</button>
				</form>
				<p class="text-[10px] text-ink-muted">Every reveal is logged with your name and reason.</p>
			{/if}
			{#if form?.message}<p class="text-xs text-alert">{form.message}</p>{/if}
		</div>
	</div>

	<!-- stats -->
	<div class="mt-6 grid grid-cols-2 gap-3 md:grid-cols-5">
		<div class="rounded-3xl bg-white p-4 shadow-card"><p class="flex items-center gap-1 text-xs text-ink-muted"><ArrowDownLeft size={12} class="text-[#16a34a]" /> Received</p><p class="mt-1 text-xl font-semibold tabular-nums">{thb(e.stats.in_satang)}</p></div>
		<div class="rounded-3xl bg-white p-4 shadow-card"><p class="flex items-center gap-1 text-xs text-ink-muted"><ArrowUpRight size={12} class="text-[#e5484d]" /> Sent</p><p class="mt-1 text-xl font-semibold tabular-nums">{thb(e.stats.out_satang)}</p></div>
		<div class="rounded-3xl bg-white p-4 shadow-card"><p class="text-xs text-ink-muted">Transfers</p><p class="mt-1 text-xl font-semibold tabular-nums">{e.stats.transfers.toLocaleString()}</p></div>
		<div class="rounded-3xl bg-white p-4 shadow-card"><p class="text-xs text-ink-muted">Counterparties</p><p class="mt-1 text-xl font-semibold tabular-nums">{e.stats.counterparties}</p></div>
		<div class="rounded-3xl bg-white p-4 shadow-card"><p class="text-xs text-ink-muted">Opened · devices</p><p class="mt-1 text-sm font-semibold">{date(p.opened_at)}</p><p class="text-[11px] text-ink-muted">{p.devices} device{p.devices === 1 ? '' : 's'} · {p.accounts_held} account{p.accounts_held === 1 ? '' : 's'} held</p></div>
	</div>

	<div class="mt-4 grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
		<!-- left: chart -->
		<div class="flex min-h-0 flex-col rounded-3xl bg-white p-5 shadow-card">
			<div class="flex items-center gap-1 text-[11px] font-medium">
				<button onclick={() => (chart = 'balance')} class="rounded-full px-3 py-1 {chart === 'balance' ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">Balance history</button>
				<button onclick={() => (chart = 'flow')} class="rounded-full px-3 py-1 {chart === 'flow' ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">Daily in / out</button>
				<span class="ml-auto text-ink-muted">{date(e.stats.first_seen)} – {date(e.stats.last_seen)}</span>
			</div>
			{#if series.length}
				<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="mt-3 min-h-40 w-full flex-1" role="img" aria-label="Balance history" onmouseleave={() => (hover = null)}>
					<line x1={PX} x2={W - PX} y1={sy(0)} y2={sy(0)} stroke="#ecf0f8" />
					{#if chart === 'balance'}
						<path d={area} fill="#6c72ac" fill-opacity="0.12" />
						<path d={line} fill="none" stroke="#6c72ac" stroke-width="2" />
					{:else}
						{#each series as h, i (h.day)}
							<rect x={sx(i) - barW / 2} y={sy(h.in_satang)} width={barW} height={Math.max(0, sy(0) - sy(h.in_satang))} rx="2" fill="#16a34a" fill-opacity="0.75" />
							<rect x={sx(i) - barW / 2} y={sy(0)} width={barW} height={Math.max(0, sy(-h.out_satang) - sy(0))} rx="2" fill="#e5484d" fill-opacity="0.75" />
						{/each}
					{/if}
					{#each series as h, i (h.day)}
						<rect role="presentation" x={sx(i) - (W / series.length) / 2} y="0" width={W / series.length} height={H} fill="transparent" onmouseenter={() => (hover = i)} />
					{/each}
					{#if hover !== null}
						<line x1={sx(hover)} x2={sx(hover)} y1={PY} y2={H - PY} stroke="#05060b" stroke-opacity="0.2" />
						{#if chart === 'balance'}<circle cx={sx(hover)} cy={sy(series[hover].balance_satang)} r="4" fill="#6c72ac" />{/if}
					{/if}
				</svg>
				<p class="h-4 text-[11px] text-ink-muted">
					{#if hover !== null}{@const h = series[hover]}{h.day} · balance {thb(h.balance_satang)} · in <span class="text-[#16a34a]">{thb(h.in_satang)}</span> · out <span class="text-[#e5484d]">{thb(h.out_satang)}</span>{:else}Running net flow over the period (synthetic data has no opening balance){/if}
				</p>
			{:else}
				<p class="mt-6 text-sm text-ink-muted">No transfers.</p>
			{/if}
		</div>

		<!-- right: tabs -->
		<div class="flex max-h-[460px] min-h-0 flex-col rounded-3xl bg-white shadow-card lg:max-h-none">
			<div class="flex gap-1 px-4 pt-4 text-[11px] font-medium">
				<button onclick={() => (tab = 'counterparties')} class="rounded-full px-3 py-1 {tab === 'counterparties' ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">Counterparties</button>
				<button onclick={() => (tab = 'transfers')} class="rounded-full px-3 py-1 {tab === 'transfers' ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">Transfers</button>
				<button onclick={() => (tab = 'cases')} class="rounded-full px-3 py-1 {tab === 'cases' ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">Cases {e.cases.length}</button>
			</div>
			<div class="min-h-0 flex-1 overflow-auto p-2">
				{#if tab === 'counterparties'}
					<table class="w-full text-left text-xs">
						<thead class="sticky top-0 bg-white text-ink-muted"><tr><th class="px-2 py-1.5 font-medium">Account</th><th class="text-right font-medium">In</th><th class="text-right font-medium">Out</th><th class="px-2 text-right font-medium">#</th></tr></thead>
						<tbody>
							{#each e.counterparties as c (c.account_id)}
								<tr class="border-t border-mist hover:bg-mist/50">
									<td class="max-w-44 truncate px-2 py-1.5"><a href="/accounts/{c.account_id}" class="hover:underline"><span class="mr-1.5 inline-block size-2 rounded-full {c.type === 'merchant' ? 'bg-ink' : riskDot(c.risk)}"></span>{c.name ?? c.account_id}</a></td>
									<td class="text-right text-[#16a34a] tabular-nums">{c.in_satang ? thb(c.in_satang) : ''}</td>
									<td class="text-right text-[#e5484d] tabular-nums">{c.out_satang ? thb(c.out_satang) : ''}</td>
									<td class="px-2 text-right text-ink-muted tabular-nums">{c.count}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{:else if tab === 'transfers'}
					<table class="w-full text-left text-xs">
						<thead class="sticky top-0 bg-white text-ink-muted"><tr><th class="px-2 py-1.5 font-medium">Time</th><th class="font-medium">Counterparty</th><th class="font-medium">Channel</th><th class="px-2 text-right font-medium">Value</th></tr></thead>
						<tbody>
							{#each e.transfers as t (t.id)}
								<tr class="border-t border-mist hover:bg-mist/50" title="{t.id} · device {t.device_id ?? '—'}">
									<td class="px-2 py-1.5 whitespace-nowrap text-ink-muted tabular-nums">{when(t.ts)}</td>
									<td class="max-w-40 truncate"><a href="/accounts/{t.counterparty}" class="hover:underline">{t.direction === 'in' ? '← ' : '→ '}{t.counterparty_name ?? t.counterparty}</a>{#if (t.counterparty_risk ?? 0) >= 70}<ShieldAlert size={11} class="ml-1 inline text-alert" />{/if}</td>
									<td class="text-ink-muted">{t.channel}</td>
									<td class="px-2 text-right font-medium tabular-nums {t.direction === 'in' ? 'text-[#16a34a]' : 'text-[#e5484d]'}">{t.direction === 'in' ? '+' : '−'}{thb(t.amount_satang)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{:else}
					<ul class="space-y-2 p-2">
						{#each e.cases as c (c.id)}
							<li><a href="/cases/{c.id}" class="flex items-center justify-between gap-2 rounded-2xl bg-mist p-3 text-xs hover:ring-1 hover:ring-haze">
								<span class="truncate font-medium">{c.title ?? c.id.slice(0, 8)}</span>
								<span class="shrink-0 text-ink-muted capitalize">{c.disposition ?? c.status}</span>
							</a></li>
						{:else}
							<li class="p-2 text-xs text-ink-muted">No cases.</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	</div>
</section>
