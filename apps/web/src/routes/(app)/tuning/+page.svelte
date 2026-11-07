<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onMount, tick } from 'svelte';
	import { browserSupabase } from '#lib/supabase.ts';
	import { FEATURE_GROUPS, RUN_TONE, type CurvePoint, type ModelVersion } from '#lib/tuning.ts';
	import { BrainCircuit, Cloud, Cpu, Eye, EyeOff, Play, RotateCcw, Trophy } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();

	const canTune = $derived(data.role === 'compliance_manager' || data.role === 'admin');
	const champion = $derived(data.models.find((m) => m.stage === 'champion'));
	const candidates = $derived(data.models.filter((m) => m.stage !== 'champion' && m.card_json?.curve));
	let pickedId = $state<string | null>(null);
	const challenger = $derived(candidates.find((m) => m.id === pickedId) ?? candidates[0]);
	const run = $derived(data.runs[0]);
	const active = $derived(run && ['queued', 'provisioning', 'running'].includes(run.status));

	let threshold = $state(0.7);
	const point = (curve: CurvePoint[] | undefined) => curve?.find((c) => Math.abs(c.threshold - threshold) < 1e-6);
	const newAt = $derived(point(challenger?.card_json.curve));
	const oldAt = $derived(point(challenger?.card_json.champion?.curve));

	let logBox: HTMLPreElement | undefined = $state();
	$effect(() => {
		void run?.log_tail;
		tick().then(() => logBox && (logBox.scrollTop = logBox.scrollHeight));
	});

	onMount(() => {
		const supabase = browserSupabase();
		let channel: ReturnType<typeof supabase.channel> | undefined;
		supabase.auth.getSession().then(({ data: { session } }) => {
			if (session) supabase.realtime.setAuth(session.access_token);
			channel = supabase
				.channel('tuning')
				.on('postgres_changes', { event: '*', schema: 'public', table: 'train_runs' }, () => invalidate('app:tuning'))
				.on('postgres_changes', { event: '*', schema: 'public', table: 'model_versions' }, () => invalidate('app:tuning'))
				.subscribe();
		});
		return () => channel && supabase.removeChannel(channel);
	});

	// trade-off chart: alerts/day (x) vs share of mule accounts caught (y)
	const W = 320, H = 170, P = 28;
	const xMax = $derived(
		Math.max(10, ...[...(challenger?.card_json.curve ?? []), ...(challenger?.card_json.champion?.curve ?? [])].map((c) => c.alerts_per_day))
	);
	const sx = (v: number) => P + (v / xMax) * (W - P - 8);
	const sy = (v: number) => H - P - v * (H - P - 10);
	const path = (curve: CurvePoint[] = []) =>
		curve.map((c, i) => `${i ? 'L' : 'M'}${sx(c.alerts_per_day).toFixed(1)},${sy(c.mules_caught).toFixed(1)}`).join(' ');

	const pct = (v: number | undefined) => (v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);
	const fmt = (v: number | undefined, d = 4) => (v === undefined ? '—' : v.toFixed(d));
	const when = (ts: string | null) =>
		ts ? new Date(ts).toLocaleString('en-GB', { timeZone: 'Asia/Bangkok', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
	const label = (m: ModelVersion | undefined) => m?.name ?? m?.id.slice(0, 8) ?? '—';
</script>

<section class="mx-auto max-w-6xl pt-4">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">Model Tuning</h1>
			<p class="mt-1 text-sm text-ink-muted">
				Champion <span class="font-medium text-ink">{label(champion)}</span>
				{#if champion?.params_json.alert_threshold}· alerts at score ≥ {champion.params_json.alert_threshold}{/if}
			</p>
		</div>
		{#if data.config}
			<span class="flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium shadow-card">
				{#if data.config.runner === 'vultr'}<Cloud size={14} class="text-accent" /> Runs on a Vultr Training VM ({data.config.plan}, {data.config.region})
				{:else}<Cpu size={14} class="text-accent" /> Runs locally (set TRAIN_RUNNER=vultr for a Training VM){/if}
			</span>
		{/if}
	</div>

	{#if form?.message}
		<p class="mt-4 rounded-2xl bg-ink px-4 py-2.5 text-sm text-white">{form.message}</p>
	{/if}

	<div class="mt-6 grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
		<!-- train form + live log -->
		<div class="space-y-5">
			<form method="POST" action="?/train" use:enhance class="space-y-4 rounded-3xl bg-white p-5 shadow-card">
				<p class="flex items-center gap-2 font-semibold"><BrainCircuit size={18} class="text-accent" /> Train a challenger</p>
				<div class="space-y-2">
					{#each FEATURE_GROUPS as [group, names] (group)}
						<div>
							<p class="text-[11px] font-medium tracking-wide text-ink-muted uppercase">{group}</p>
							<div class="mt-1 flex flex-wrap gap-1.5">
								{#each names as f (f)}
									<label class="cursor-pointer">
										<input type="checkbox" name="f_{f}" checked class="peer sr-only" />
										<span class="block rounded-full bg-mist px-2.5 py-1 text-[11px] text-ink-muted line-through peer-checked:bg-ink peer-checked:text-white peer-checked:no-underline">{f}</span>
									</label>
								{/each}
							</div>
						</div>
					{/each}
				</div>
				<div class="grid grid-cols-3 gap-2 text-xs">
					<label class="space-y-1"><span class="text-ink-muted">learning rate</span>
						<input name="learning_rate" type="number" step="0.01" min="0.01" max="1" placeholder="0.05" class="w-full rounded-xl bg-mist px-3 py-2" /></label>
					<label class="space-y-1"><span class="text-ink-muted">num_leaves</span>
						<input name="num_leaves" type="number" min="4" max="512" placeholder="31" class="w-full rounded-xl bg-mist px-3 py-2" /></label>
					<label class="space-y-1"><span class="text-ink-muted">class weight</span>
						<input name="scale_pos_weight" type="number" step="0.5" min="0.5" max="200" placeholder="20" class="w-full rounded-xl bg-mist px-3 py-2" /></label>
				</div>
				<label class="flex items-center justify-between gap-3 text-xs"><span class="text-ink-muted">Optuna search trials (0 = use the values above)</span>
					<input name="trials" type="number" min="0" max="40" value="6" class="w-16 rounded-xl bg-mist px-3 py-2 text-right" /></label>
				<label class="flex items-center gap-2 text-xs"><input type="checkbox" name="use_analyst_labels" checked class="accent-[#05060b]" />
					Add the live month labelled by analyst decisions</label>
				<button disabled={!canTune || active} class="flex w-full items-center justify-center gap-2 rounded-full bg-ink py-2.5 text-sm font-medium text-white disabled:opacity-40">
					<Play size={14} /> {active ? 'Training in progress…' : 'Train'}
				</button>
				{#if !canTune}<p class="text-center text-xs text-ink-muted">Only the Compliance Manager (model owner) can train and promote.</p>{/if}
			</form>

			{#if run}
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between gap-2">
						<p class="font-semibold">Latest run</p>
						<span class="rounded-full px-2.5 py-1 text-xs font-semibold capitalize {RUN_TONE[run.status]}" data-testid="run-status">{run.status}</span>
					</div>
					<p class="mt-1 text-xs text-ink-muted">
						{run.runner === 'vultr' ? 'Vultr Training VM' : 'local process'}{run.vultr_instance_id ? ` · instance ${run.vultr_instance_id}` : ''} · {when(run.created_at)}
					</p>
					<pre bind:this={logBox} class="mt-3 max-h-72 overflow-auto rounded-2xl bg-ink p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-white/85">{run.log_tail ?? 'waiting for the job…'}</pre>
					{#if run.error}<p class="mt-2 text-xs text-alert">{run.error.split('\n').filter(Boolean).at(-1)}</p>{/if}
				</div>
			{/if}
		</div>

		<!-- champion vs challenger -->
		<div class="space-y-5">
			{#if challenger}
				{@const card = challenger.card_json}
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<p class="flex items-center gap-2 font-semibold"><Trophy size={18} class="text-alert" /> Champion vs Challenger</p>
						{#if candidates.length > 1}
							<select bind:value={pickedId} class="rounded-full bg-mist px-3 py-1.5 text-xs">
								{#each candidates as m (m.id)}<option value={m.id}>{label(m)} · {m.stage}</option>{/each}
							</select>
						{/if}
					</div>
					<p class="mt-1 text-xs text-ink-muted">
						Same holdout for both: unseen synthetic month (seed {card.holdout?.seed}), {card.holdout?.rows.toLocaleString()} scored rows,
						{card.holdout?.fraud_rows.toLocaleString()} fraud. Trained on {card.training?.rows.toLocaleString()} rows in {card.seconds?.toFixed(0)}s.
					</p>

					<table class="mt-4 w-full text-sm">
						<thead><tr class="text-left text-xs text-ink-muted">
							<th class="py-1 font-medium"></th>
							<th class="py-1 text-right font-medium">{card.champion?.name ?? 'champion'}</th>
							<th class="py-1 text-right font-medium text-ink">{label(challenger)}</th>
						</tr></thead>
						<tbody class="tabular-nums">
							<tr class="border-t border-mist"><td class="py-1.5">PR-AUC</td><td class="text-right">{fmt(card.champion?.pr_auc)}</td><td class="text-right font-semibold">{fmt(challenger.metrics_json.pr_auc as number)}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Precision @ top 100</td><td class="text-right">{pct(card.champion?.precision_at_100)}</td><td class="text-right font-semibold">{pct(challenger.metrics_json.precision_at_100 as number)}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Mule accounts caught @ {threshold.toFixed(2)}</td><td class="text-right">{pct(oldAt?.mules_caught)}</td><td class="text-right font-semibold">{pct(newAt?.mules_caught)}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Fraud rows recalled</td><td class="text-right">{pct(oldAt?.recall)}</td><td class="text-right font-semibold">{pct(newAt?.recall)}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Precision</td><td class="text-right">{pct(oldAt?.precision)}</td><td class="text-right font-semibold">{pct(newAt?.precision)}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Alerts per day (analyst workload)</td><td class="text-right">{oldAt?.alerts_per_day ?? '—'}</td><td class="text-right font-semibold">{newAt?.alerts_per_day ?? '—'}</td></tr>
							<tr class="border-t border-mist"><td class="py-1.5">Clean accounts flagged</td><td class="text-right">{oldAt?.clean_accounts_flagged ?? '—'}</td><td class="text-right font-semibold">{newAt?.clean_accounts_flagged ?? '—'}</td></tr>
						</tbody>
					</table>
					<p class="mt-2 text-xs text-ink-muted">
						At threshold 0.70 the challenger catches <b class="text-ink">{card.gained_accounts?.length ?? 0}</b> mule accounts the champion misses and misses
						<b class="text-ink">{card.lost_accounts?.length ?? 0}</b> it catches.
					</p>

					<div class="mt-4 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-center">
						<svg viewBox="0 0 {W} {H}" class="w-full" role="img" aria-label="Mules caught versus alerts per day">
							<line x1={P} y1={H - P} x2={W - 8} y2={H - P} stroke="#d9ddf0" />
							<line x1={P} y1={10} x2={P} y2={H - P} stroke="#d9ddf0" />
							<text x={P} y={H - 8} font-size="9" fill="#4d506e">alerts / day →</text>
							<text x={2} y={14} font-size="9" fill="#4d506e">caught</text>
							<path d={path(card.champion?.curve)} fill="none" stroke="#9ca7de" stroke-width="2" />
							<path d={path(card.curve)} fill="none" stroke="#ec630d" stroke-width="2" />
							{#if oldAt}<circle cx={sx(oldAt.alerts_per_day)} cy={sy(oldAt.mules_caught)} r="4" fill="#9ca7de" />{/if}
							{#if newAt}<circle cx={sx(newAt.alerts_per_day)} cy={sy(newAt.mules_caught)} r="4.5" fill="#ec630d" stroke="#fff" stroke-width="1.5" />{/if}
						</svg>
						<div class="flex gap-3 text-xs sm:flex-col">
							<span class="flex items-center gap-1.5"><span class="h-0.5 w-4 bg-[#9ca7de]"></span>champion</span>
							<span class="flex items-center gap-1.5"><span class="h-0.5 w-4 bg-alert"></span>challenger</span>
						</div>
					</div>
					<label class="mt-2 flex items-center gap-3 text-xs">
						<span class="shrink-0 text-ink-muted">Score threshold</span>
						<input type="range" min="0.05" max="0.95" step="0.05" bind:value={threshold} class="flex-1 accent-[#ec630d]" />
						<span class="w-10 text-right font-semibold tabular-nums">{Math.round(threshold * 100)}</span>
					</label>

					{#if challenger.stage === 'shadow' && challenger.shadow_json}
						{@const s = challenger.shadow_json}
						<p class="mt-3 rounded-2xl bg-mist p-3 text-xs">
							<b>Shadow (live):</b> {s.rows.toLocaleString()} rows scored · would alert on {s.would_alert.toLocaleString()} vs champion
							{s.champion_alerts.toLocaleString()} · agree on {s.both.toLocaleString()}
						</p>
					{/if}

					<div class="mt-4 flex flex-wrap gap-2">
						<form method="POST" action="?/promote" use:enhance>
							<input type="hidden" name="id" value={challenger.id} />
							<input type="hidden" name="alert_threshold" value={Math.round(threshold * 100)} />
							<button disabled={!canTune} class="rounded-full bg-ink px-4 py-2 text-xs font-medium text-white disabled:opacity-40">
								Promote at threshold {Math.round(threshold * 100)}
							</button>
						</form>
						<form method="POST" action="?/shadow" use:enhance>
							<input type="hidden" name="id" value={challenger.id} />
							<input type="hidden" name="stage" value={challenger.stage === 'shadow' ? 'challenger' : 'shadow'} />
							<button disabled={!canTune} class="flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-xs font-medium ring-1 ring-ink/15 disabled:opacity-40">
								{#if challenger.stage === 'shadow'}<EyeOff size={14} /> Stop shadow{:else}<Eye size={14} /> Run in shadow{/if}
							</button>
						</form>
					</div>
				</div>
			{:else}
				<div class="rounded-3xl bg-white p-10 text-center text-sm text-ink-muted shadow-card">
					No challenger yet. Train one to compare it with the champion on the same holdout month.
				</div>
			{/if}

			<div class="rounded-3xl bg-white p-5 shadow-card">
				<div class="flex items-center justify-between">
					<p class="font-semibold">Model registry</p>
					<form method="POST" action="?/rollback" use:enhance>
						<button disabled={!canTune} class="flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium ring-1 ring-ink/15 disabled:opacity-40">
							<RotateCcw size={13} /> Roll back champion
						</button>
					</form>
				</div>
				<ul class="mt-3 divide-y divide-mist text-sm">
					{#each data.models as m (m.id)}
						<li class="flex items-center gap-3 py-2">
							<span class="w-24 shrink-0 rounded-full px-2.5 py-0.5 text-center text-xs font-semibold capitalize
								{m.stage === 'champion' ? 'bg-alert text-white' : m.stage === 'shadow' ? 'bg-accent text-white' : 'bg-mist text-ink-muted'}">{m.stage}</span>
							<span class="min-w-0 flex-1 truncate font-medium">{label(m)}</span>
							<span class="text-xs text-ink-muted tabular-nums">PR-AUC {fmt(m.metrics_json.pr_auc as number)}</span>
							<span class="hidden w-28 text-right text-xs text-ink-muted sm:block">{m.promoted_at ? `promoted ${when(m.promoted_at)}` : when(m.created_at)}</span>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	</div>
</section>
