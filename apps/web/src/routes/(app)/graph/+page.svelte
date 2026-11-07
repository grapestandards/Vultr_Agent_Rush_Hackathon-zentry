<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { Core, ElementDefinition, LayoutOptions } from 'cytoscape';
	import { onMount } from 'svelte';
	import type { GraphNode, GraphTxn, Network, Trace } from '#lib/graph.ts';
	import { thb } from '#lib/money.ts';
	import { RISK_TONE } from '#lib/cases.ts';
	import { Boxes, Crosshair, Maximize, Pause, Play, Plus, Search, X } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let container: HTMLDivElement | undefined = $state();
	let cy: Core | undefined;
	// Graph state lives outside $state: Cytoscape owns rendering, Svelte only shows panels.
	const nodes = new Map<string, GraphNode>();
	const txns = new Map<string, GraphTxn>();
	let win = $state({ start: 0, end: 1 });
	let at = $state(1); // time slider position (ms)
	let playing = $state(false);
	let showGroups = $state(true);
	let selected: GraphNode | null = $state(null);
	let selectedGroup: Network['groups'][number] | null = $state(null);
	let trace: Trace | null = $state(null);
	let busy = $state(false);
	let message = $state('');
	let counts = $state({ nodes: 0, edges: 0, flagged: 0 });
	let search = $state('');

	const caseId = page.url.searchParams.get('case');
	const RISK_HIGH = '#ec630d';
	const RISK_MED = '#f4a46a';

	function nodeEl(n: GraphNode, parent?: string): ElementDefinition {
		const flow = Math.max(n.in_satang, n.out_satang) / 100;
		const classes = [
			n.type === 'merchant' ? 'merchant' : '',
			(n.risk ?? 0) >= 90 ? 'risk-high' : (n.risk ?? 0) >= 70 ? 'risk-med' : '',
			n.status === 'frozen' ? 'frozen' : '',
			data.network?.seeds.includes(n.id) ? 'seed' : ''
		];
		return {
			group: 'nodes',
			data: {
				id: n.id,
				parent,
				label: n.type === 'merchant' ? n.name_en : n.name_en.split(' ')[0],
				size: 22 + 7 * Math.log10(1 + flow)
			},
			classes: classes.filter(Boolean).join(' ')
		};
	}

	/** One edge per (from, to) pair; the slider decides which of its transfers have happened yet. */
	function pairEdges(list: GraphTxn[]): Map<string, GraphTxn[]> {
		const pairs = new Map<string, GraphTxn[]>();
		for (const t of list) {
			const k = `${t.from_account}>${t.to_account}`;
			pairs.set(k, [...(pairs.get(k) ?? []), t]);
		}
		return pairs;
	}

	function addNetwork(net: Network, withGroups: boolean) {
		if (!cy) return;
		const groupOf = new Map<string, string>();
		const els: ElementDefinition[] = [];
		if (withGroups) {
			for (const g of net.groups) {
				if (cy.getElementById(g.id).nonempty()) continue;
				els.push({ group: 'nodes', data: { id: g.id, label: `Network · ${g.members.length} accounts` }, classes: 'group' });
				for (const m of g.members) groupOf.set(m, g.id);
			}
		}
		for (const n of net.nodes) {
			nodes.set(n.id, n);
			if (cy.getElementById(n.id).empty()) els.push(nodeEl(n, groupOf.get(n.id)));
		}
		for (const t of net.transactions) txns.set(t.id, t);
		cy.add(els);
		syncEdges();
	}

	function syncEdges() {
		if (!cy) return;
		for (const [k, list] of pairEdges([...txns.values()])) {
			const total = list.reduce((s, t) => s + t.amount_satang, 0);
			const e = cy.getElementById(k);
			const d = { id: k, source: list[0].from_account, target: list[0].to_account, total, n: list.length,
				first: Math.min(...list.map((t) => +new Date(t.ts))), width: 1 + 1.6 * Math.log10(1 + total / 100 / 1000) };
			if (e.empty()) cy.add({ group: 'edges', data: d });
			else e.data(d);
		}
		applyTime();
	}

	/** Hide what has not happened yet at slider time `at`. */
	function applyTime() {
		if (!cy) return;
		cy.batch(() => {
			cy!.edges().forEach((e) => {
				e.toggleClass('future', e.data('first') > at);
			});
			cy!.nodes().not('.group').forEach((n) => {
				const live = n.connectedEdges().not('.future').nonempty() || n.hasClass('seed');
				n.toggleClass('future', !live);
			});
		});
		const visible = cy.nodes().not('.group').not('.future');
		counts = {
			nodes: visible.length,
			edges: cy.edges().not('.future').length,
			flagged: visible.filter((n) => n.hasClass('risk-high') || n.hasClass('risk-med')).length
		};
	}

	function layout(opts: Partial<LayoutOptions> = {}) {
		cy?.layout({
			name: 'fcose',
			animate: true,
			animationDuration: 500,
			nodeRepulsion: 9000,
			idealEdgeLength: 90,
			nestingFactor: 0.6,
			packComponents: true,
			...opts
		} as unknown as LayoutOptions).run();
	}

	async function expand(id: string) {
		busy = true;
		const q = new URLSearchParams({ kind: 'network', start: data.network!.window.start, end: data.network!.window.end });
		q.append('accounts', id);
		const r = await fetch(`/graph/data?${q}`);
		busy = false;
		if (!r.ok) return (message = (await r.json()).detail ?? 'Expand failed');
		const before = cy!.nodes().length;
		addNetwork(await r.json(), false);
		message = `+${cy!.nodes().length - before} accounts around ${id}`;
		layout({ randomize: false });
	}

	async function runTrace(victim?: string) {
		busy = true;
		const q = new URLSearchParams(caseId ? { kind: 'trace', case: caseId } : { kind: 'trace', account: data.network!.seeds[0] });
		if (victim) q.set('victim', victim);
		const r = await fetch(`/graph/data?${q}`);
		busy = false;
		if (!r.ok) return (message = (await r.json()).detail ?? 'Trace failed');
		showTrace(await r.json());
	}

	function showTrace(t: Trace) {
		if (!cy) return;
		clearTrace(false);
		trace = t;
		const fresh = t.nodes.filter((n) => !nodes.has(n.id));
		addNetwork({ window: data.network!.window, seeds: [], nodes: fresh, transactions: t.path, groups: [] }, false);
		at = win.end;
		applyTime();
		const held = new Map(t.held.map((h) => [h.account_id, h.satang]));
		const cashed = new Map(t.cash_out.map((h) => [h.account_id, h.satang]));
		const onPath = new Set(t.path.flatMap((p) => [p.from_account, p.to_account]));
		const pairs = new Set(t.path.map((p) => `${p.from_account}>${p.to_account}`));
		cy.batch(() => {
			cy!.elements().addClass('faded');
			cy!.nodes('.group').removeClass('faded');
			for (const id of onPath) {
				const n = cy!.getElementById(id).removeClass('faded').addClass('traced');
				const h = held.get(id) ?? cashed.get(id);
				const base = nodes.get(id)!;
				n.data('label', h ? `${base.name_en.split(' ')[0]} · ${thb(h)}` : n.data('label'));
				n.toggleClass('holding', held.has(id) && (held.get(id) ?? 0) > 0);
			}
			cy!.getElementById(t.victim).addClass('victim');
			for (const k of pairs) cy!.getElementById(k).removeClass('faded').addClass('traced');
		});
		// Layers read best outside the network boxes: victim → collectors → splitters → cash-out.
		setGroups(false);
		const path = cy.getElementById(t.victim).union(cy.elements('.traced'));
		const lay = path.layout({ name: 'breadthfirst', directed: true, roots: `#${t.victim}`, spacingFactor: 1.1,
			animate: false, fit: false } as LayoutOptions);
		lay.one('layoutstop', () => {
			cy!.fit(path, 70);
			// leave room for the trace panel on the right
			cy!.zoom({ level: cy!.zoom() * 0.72, renderedPosition: { x: 40, y: cy!.height() * 0.45 } });
		});
		lay.run();
		const url = new URL(page.url.href);
		url.searchParams.set('trace', '1');
		url.searchParams.set('victim', t.victim);
		history.replaceState(history.state, '', url);
	}

	function clearTrace(relayout = true) {
		if (!cy || !trace) return;
		cy.batch(() => {
			cy!.elements().removeClass('faded traced victim holding');
			cy!.nodes().not('.group').forEach((n) => {
				const base = nodes.get(n.id());
				if (base) n.data('label', base.type === 'merchant' ? base.name_en : base.name_en.split(' ')[0]);
			});
		});
		trace = null;
		setGroups(showGroups);
		const url = new URL(page.url.href);
		url.searchParams.delete('trace');
		url.searchParams.delete('victim');
		history.replaceState(history.state, '', url);
		if (relayout) layout();
	}

	function setGroups(on: boolean) {
		if (!cy || !data.network) return;
		cy.batch(() => {
			for (const g of data.network!.groups) {
				for (const m of g.members) {
					const n = cy!.getElementById(m);
					if (n.nonempty() && (n.data('parent') ?? null) !== (on ? g.id : null)) n.move({ parent: on ? g.id : null });
				}
			}
			cy!.nodes('.group').style('display', on ? 'element' : 'none');
		});
	}

	function toggleGroups() {
		showGroups = !showGroups;
		if (trace) return; // trace view keeps boxes off; they come back on exit
		setGroups(showGroups);
		layout();
	}

	let timer: ReturnType<typeof setInterval> | undefined;
	function play() {
		if (playing) {
			clearInterval(timer);
			playing = false;
			return;
		}
		if (at >= win.end) at = win.start;
		playing = true;
		const step = (win.end - win.start) / 240; // ~12 s for the whole window
		timer = setInterval(() => {
			at = Math.min(win.end, at + step);
			applyTime();
			if (at >= win.end) {
				clearInterval(timer);
				playing = false;
			}
		}, 50);
	}

	onMount(() => {
		if (!data.network || !container) return;
		let destroyed = false;
		(async () => {
			const [{ default: cytoscape }, { default: fcose }] = await Promise.all([import('cytoscape'), import('cytoscape-fcose')]);
			if (destroyed) return;
			cytoscape.use(fcose);
			cy = cytoscape({
				container,
				minZoom: 0.15,
				maxZoom: 3,
				wheelSensitivity: 0.3,
				style: [
					{ selector: 'node', style: {
						'background-color': '#9ca7de', width: 'data(size)', height: 'data(size)', label: 'data(label)',
						'font-size': 9, 'font-family': 'Inter, sans-serif', color: '#4d506e', 'text-valign': 'bottom',
						'text-margin-y': 4, 'border-width': 2, 'border-color': '#fff', 'transition-property': 'opacity', 'transition-duration': 200 } },
					{ selector: 'node.risk-med', style: { 'background-color': RISK_MED } },
					{ selector: 'node.risk-high', style: { 'background-color': RISK_HIGH } },
					{ selector: 'node.merchant', style: { shape: 'round-rectangle', 'background-color': '#05060b', color: '#05060b', 'font-weight': 600 } },
					{ selector: 'node.seed', style: { 'border-color': '#05060b', 'border-width': 2.5 } },
					{ selector: 'node.frozen', style: { 'border-color': '#6c72ac', 'border-width': 4, 'border-style': 'double' } },
					{ selector: 'node.victim', style: { 'background-color': '#6c72ac', 'border-color': '#fff', 'border-width': 4, 'font-weight': 700, color: '#05060b' } },
					{ selector: 'node.holding', style: { 'border-color': '#ec630d', 'border-width': 5, 'font-weight': 700, color: '#ec630d' } },
					{ selector: 'node.group', style: {
						'background-color': '#ecf0f8', 'background-opacity': 0.55, 'border-color': '#9ca7de', 'border-width': 1.5,
						'border-style': 'dashed', shape: 'round-rectangle', label: 'data(label)', 'text-valign': 'top',
						'font-size': 10, 'font-weight': 600, color: '#6c72ac', padding: '18px' } },
					{ selector: 'node:selected', style: { 'overlay-color': '#6c72ac', 'overlay-opacity': 0.18, 'overlay-padding': 6 } },
					{ selector: 'edge', style: {
						width: 'data(width)', 'line-color': '#b8bfe6', 'target-arrow-color': '#b8bfe6', 'target-arrow-shape': 'triangle',
						'arrow-scale': 0.8, 'curve-style': 'bezier', opacity: 0.85 } },
					{ selector: 'edge.traced', style: { 'line-color': '#ec630d', 'target-arrow-color': '#ec630d', opacity: 1, 'z-index': 10 } },
					{ selector: '.faded', style: { display: 'none' } },
					{ selector: '.future', style: { display: 'none' } }
				]
			});
			win = { start: +new Date(data.network!.window.start), end: +new Date(data.network!.window.end) };
			at = win.end;
			addNetwork(data.network!, true);
			cy.on('tap', 'node', (e) => {
				const n = e.target;
				if (n.hasClass('group')) {
					selectedGroup = data.network!.groups.find((g) => g.id === n.id()) ?? null;
					selected = null;
				} else {
					selected = nodes.get(n.id()) ?? null;
					selectedGroup = null;
				}
			});
			cy.on('dbltap', 'node', (e) => {
				if (!e.target.hasClass('group')) expand(e.target.id());
			});
			cy.on('tap', (e) => {
				if (e.target === cy) selected = selectedGroup = null;
			});
			if (data.trace) {
				cy.one('layoutstop', () => showTrace(data.trace!));
			}
			layout({ randomize: true, animate: false });
		})();
		return () => {
			destroyed = true;
			clearInterval(timer);
			cy?.destroy();
		};
	});

	const fmtTime = (ms: number) =>
		new Date(ms).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Bangkok' });
	const nodeName = (id: string) => nodes.get(id)?.name_en ?? id;
</script>

{#if !data.network}
	<section class="mx-auto max-w-3xl pt-4">
		<h1 class="text-3xl font-semibold tracking-tight">Graph Explorer</h1>
		{#if data.error}<p class="mt-3 rounded-2xl bg-white p-4 text-sm text-alert shadow-card">{data.error}</p>{/if}
		<form class="mt-6 flex gap-2" onsubmit={(e) => { e.preventDefault(); if (search.trim()) goto(`/graph?account=${search.trim()}`); }}>
			<label class="flex flex-1 items-center gap-2 rounded-full bg-white px-4 py-2.5 shadow-card">
				<Search size={16} class="text-ink-muted" />
				<input bind:value={search} placeholder="Account id, e.g. A0001234" class="flex-1 bg-transparent text-sm outline-none" />
			</label>
			<button class="rounded-full bg-ink px-5 text-sm font-medium text-white">Open</button>
		</form>
		<p class="mt-8 text-sm font-medium text-ink-muted">Or open a case network</p>
		<ul class="mt-3 space-y-2">
			{#each data.cases as c (c.id)}
				<li>
					<a href="/graph?case={c.id}" class="flex items-center gap-3 rounded-2xl bg-white p-4 shadow-card hover:ring-2 hover:ring-accent/30">
						<span class="rounded-full px-2.5 py-1 text-xs font-semibold capitalize {RISK_TONE[c.risk_level ?? 'low']}">{c.risk_level ?? 'new'}</span>
						<span class="truncate font-medium">{c.title}</span>
					</a>
				</li>
			{/each}
		</ul>
	</section>
{:else}
	<section class="relative -mx-2 h-[calc(100vh-8.5rem)] min-h-[520px] overflow-hidden rounded-3xl bg-white/60 shadow-card sm:-mx-4">
		<div bind:this={container} class="h-full w-full" data-testid="graph"></div>

		<!-- top bar -->
		<div class="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start gap-2">
			<div class="pointer-events-auto rounded-2xl bg-white/90 px-4 py-2.5 shadow-card backdrop-blur">
				<p class="text-sm font-semibold">
					{counts.nodes} accounts · <span class="text-alert">{counts.flagged} flagged</span>
				</p>
				<p class="text-xs text-ink-muted">{counts.edges} money flows · {data.network.groups.length} networks{#if caseId} · <a href="/cases/{caseId}" class="text-accent hover:underline">back to case</a>{/if}</p>
			</div>
			<div class="pointer-events-auto ml-auto flex flex-wrap gap-2">
				<button onclick={() => (trace ? clearTrace() : runTrace())} disabled={busy}
					class="flex items-center gap-1.5 rounded-full px-4 py-2 text-xs font-medium shadow-card {trace ? 'bg-alert text-white' : 'bg-ink text-white'}">
					{#if trace}<X size={14} /> Exit trace{:else}<Crosshair size={14} /> Trace from victim{/if}
				</button>
				<button onclick={toggleGroups} class="flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-xs font-medium shadow-card {showGroups ? 'ring-2 ring-accent/40' : ''}">
					<Boxes size={14} /> Networks
				</button>
				<button onclick={() => cy?.fit(undefined, 40)} title="Fit to screen" class="grid size-8 place-items-center rounded-full bg-white shadow-card"><Maximize size={14} /></button>
			</div>
		</div>

		{#if message || data.error}
			<p class="absolute top-20 left-3 rounded-full bg-ink px-3 py-1 text-xs text-white">{message || data.error}</p>
		{/if}

		<!-- side panel: trace summary, selected account or network -->
		{#if trace || selected || selectedGroup}
			<aside class="absolute top-20 right-3 bottom-24 flex w-80 max-w-[calc(100%-1.5rem)] flex-col gap-3 overflow-y-auto rounded-3xl bg-white/95 p-4 shadow-panel backdrop-blur">
				{#if selected}
					{@const n = selected}
					<div class="flex items-start justify-between gap-2">
						<div>
							<p class="font-semibold">{n.name_en}</p>
							<p class="text-xs text-ink-muted">{n.id} · {n.type} · KYC {n.kyc_level}</p>
						</div>
						<button onclick={() => (selected = null)} class="text-ink-muted"><X size={16} /></button>
					</div>
					<div class="flex flex-wrap gap-1.5 text-xs">
						{#if n.risk}<span class="rounded-full bg-alert/10 px-2.5 py-1 font-semibold text-alert">risk {n.risk}</span>{/if}
						<span class="rounded-full px-2.5 py-1 {n.status === 'frozen' ? 'bg-accent text-white' : 'bg-mist'}">{n.status}</span>
					</div>
					<dl class="grid grid-cols-2 gap-2 text-sm">
						<div class="rounded-2xl bg-mist p-3"><dt class="text-xs text-ink-muted">In (window)</dt><dd class="font-semibold tabular-nums">{thb(n.in_satang)}</dd></div>
						<div class="rounded-2xl bg-mist p-3"><dt class="text-xs text-ink-muted">Out (window)</dt><dd class="font-semibold tabular-nums">{thb(n.out_satang)}</dd></div>
					</dl>
					<button onclick={() => expand(n.id)} disabled={busy} class="flex items-center justify-center gap-1.5 rounded-full bg-ink py-2 text-xs font-medium text-white disabled:opacity-50">
						<Plus size={14} /> Expand 1 hop
					</button>
					{#if !n.risk && n.type !== 'merchant'}
						<button onclick={() => runTrace(n.id)} disabled={busy} class="rounded-full bg-white py-2 text-xs font-medium ring-1 ring-ink/15">Trace from this account as victim</button>
					{/if}
					{#each n.cases as c (c)}
						<a href="/cases/{c}" class="text-xs font-medium text-accent hover:underline">Open case →</a>
					{/each}
				{:else if selectedGroup}
					{@const g = selectedGroup}
					<p class="font-semibold">Network of {g.members.length} accounts</p>
					<p class="text-sm text-ink-muted">{g.flagged} flagged by the scorer. Flagged accounts connected by money flow in this window, plus pass-through accounts between them.</p>
					{#if g.case_id}
						<a href="/cases/{g.case_id}" class="rounded-full bg-ink py-2 text-center text-xs font-medium text-white">Open network case</a>
					{/if}
					<ul class="space-y-1 text-xs">
						{#each g.members as m (m)}<li class="flex justify-between"><span>{nodeName(m)}</span><span class="text-ink-muted">{m}</span></li>{/each}
					</ul>
				{:else if trace}
					{@const t = trace}
					<p class="text-xs font-medium tracking-wide text-ink-muted uppercase">Trace from victim</p>
					<p class="font-semibold">{nodeName(t.victim)} <span class="text-xs font-normal text-ink-muted">{t.victim}</span></p>
					<div class="space-y-2 text-sm">
						<div class="flex justify-between rounded-2xl bg-mist p-3"><span>Paid into network</span><span class="font-semibold tabular-nums">{thb(t.paid_satang)}</span></div>
						<div class="flex justify-between rounded-2xl bg-alert/10 p-3 text-alert"><span>Still held · {t.held.length} accounts</span><span class="font-semibold tabular-nums">{thb(t.held_satang)}</span></div>
						<div class="flex justify-between rounded-2xl bg-ink p-3 text-white"><span>Cashed out at merchants</span><span class="font-semibold tabular-nums">{thb(t.cashed_out_satang)}</span></div>
					</div>
					<p class="text-xs text-ink-muted">Proportional rule: each transfer carries the victim's share of the sender's balance.</p>
					<p class="text-xs font-medium text-ink-muted">Where it is held</p>
					<ul class="space-y-1 text-xs">
						{#each t.held as h (h.account_id)}
							<li class="flex justify-between"><span>{nodeName(h.account_id)} <span class="text-ink-muted">{h.account_id}</span></span><span class="font-semibold tabular-nums">{thb(h.satang)}</span></li>
						{/each}
					</ul>
					{#if t.candidates.length > 1}
						<p class="text-xs font-medium text-ink-muted">Other likely victims</p>
						<div class="flex flex-wrap gap-1.5">
							{#each t.candidates as c (c.account_id)}
								<button onclick={() => runTrace(c.account_id)} class="rounded-full px-2.5 py-1 text-xs {c.account_id === t.victim ? 'bg-ink text-white' : 'bg-mist hover:bg-haze/40'}">
									{c.name_en.split(' ')[0]} · {thb(c.paid_satang)}
								</button>
							{/each}
						</div>
					{/if}
				{/if}
			</aside>
		{/if}

		<!-- time slider -->
		<div class="absolute inset-x-3 bottom-3 flex items-center gap-3 rounded-2xl bg-white/90 px-4 py-3 shadow-card backdrop-blur">
			<button onclick={play} class="grid size-9 shrink-0 place-items-center rounded-full bg-ink text-white" title={playing ? 'Pause' : 'Replay money flow'}>
				{#if playing}<Pause size={14} />{:else}<Play size={14} />{/if}
			</button>
			<input type="range" min={win.start} max={win.end} step={60_000} bind:value={at} oninput={applyTime} class="flex-1 accent-[#ec630d]" aria-label="Time" />
			<span class="w-28 shrink-0 text-right text-xs font-medium tabular-nums">{fmtTime(at)}</span>
		</div>
		<p class="absolute bottom-20 left-4 text-[11px] text-ink-muted">Click an account for details · double-click to expand</p>
	</section>
{/if}
