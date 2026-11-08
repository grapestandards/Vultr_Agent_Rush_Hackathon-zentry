<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { Core, ElementDefinition, LayoutOptions } from 'cytoscape';
	import { onMount } from 'svelte';
	import type { GraphNode, GraphTxn, Network, Trace } from '#lib/graph.ts';
	import { thb } from '#lib/money.ts';
	import { RISK_TONE } from '#lib/cases.ts';
	import {
		Boxes, ChevronDown, Crosshair, ExternalLink, Lock, LockOpen, Maximize, Minus, Pause, Play, Plus, Search,
		Shuffle, X
	} from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let container: HTMLDivElement | undefined = $state();
	let cy: Core | undefined;
	// Graph state lives outside $state: Cytoscape owns rendering, Svelte only shows panels.
	const nodes = new Map<string, GraphNode>();
	const txns = new Map<string, GraphTxn>();
	let version = $state(0); // bumped when nodes / txns change so the panels recompute
	let win = $state({ start: 0, end: 1 });
	let at = $state(1); // time slider position (ms)
	let playing = $state(false);
	let showGroups = $state(true);
	let locked = $state(false);
	let selected = $state<GraphNode | null>(null);
	let selectedGroup: Network['groups'][number] | null = $state(null);
	let trace: Trace | null = $state(null);
	let busy = $state(false);
	let message = $state('');
	let search = $state('');
	let tab = $state<'all' | 'in' | 'out' | 'within'>('all');
	let minBaht = $state(0);
	let detailsOpen = $state(true);
	let zoomPct = $state(100);

	const caseId = page.url.searchParams.get('case');
	const RISK_HIGH = '#ec630d';
	const RISK_MED = '#f4a46a';
	const IN = '#16a34a';
	const OUT = '#e5484d';

	const short = (n: GraphNode) => n.name;
	const initialNames = $derived(new Map((data.network?.nodes ?? []).map((n) => [n.id, n.name])));
	const nodeName = (id: string) => nodes.get(id)?.name ?? initialNames.get(id) ?? id;

	/** Accounts the flow colours are relative to: the selected account, else the case / searched accounts. */
	const focus = $derived(new Set(selected ? [selected.id] : (data.network?.seeds ?? [])));

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
			data: { id: n.id, parent, label: short(n), size: 26 + 8 * Math.log10(1 + flow) },
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
		version++;
	}

	function syncEdges() {
		if (!cy) return;
		for (const [k, list] of pairEdges([...txns.values()])) {
			const total = list.reduce((s, t) => s + t.amount_satang, 0);
			const e = cy.getElementById(k);
			const d = { id: k, source: list[0].from_account, target: list[0].to_account, total, n: list.length,
				first: Math.min(...list.map((t) => +new Date(t.ts))), width: 1.2 + 1.6 * Math.log10(1 + total / 100 / 1000) };
			if (e.empty()) cy.add({ group: 'edges', data: d });
			else e.data(d);
		}
		applyTime();
		recolor();
	}

	/** Green = money into the focus accounts, red = money out of them. */
	function recolor() {
		if (!cy) return;
		cy.batch(() => {
			cy!.edges().forEach((e) => {
				const into = focus.has(e.data('target'));
				const from = focus.has(e.data('source'));
				e.toggleClass('in', into && !from);
				e.toggleClass('out', from && !into);
			});
		});
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
		version++;
	}

	function layout(opts: Partial<LayoutOptions> = {}) {
		cy?.layout({
			name: 'fcose',
			animate: true,
			animationDuration: 500,
			nodeRepulsion: 12000,
			idealEdgeLength: 110,
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
		message = `+${cy!.nodes().length - before} accounts around ${nodeName(id)}`;
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
		detailsOpen = true;
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
				n.data('label', h ? `${short(base)}\n${thb(h)}` : n.data('label'));
				n.toggleClass('holding', held.has(id) && (held.get(id) ?? 0) > 0);
			}
			cy!.getElementById(t.victim).addClass('victim');
			for (const k of pairs) cy!.getElementById(k).removeClass('faded').addClass('traced');
		});
		// Layers read best outside the network boxes: victim → collectors → splitters → cash-out.
		setGroups(false);
		const path = cy.getElementById(t.victim).union(cy.elements('.traced'));
		const lay = path.layout({ name: 'breadthfirst', directed: true, roots: `#${t.victim}`, spacingFactor: 1.15,
			animate: false, fit: false } as LayoutOptions);
		lay.one('layoutstop', () => cy!.fit(path, 90));
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
				if (base) n.data('label', short(base));
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

	function zoomBy(f: number) {
		if (!cy) return;
		cy.zoom({ level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
	}

	function toggleLock() {
		locked = !locked;
		cy?.autolock(locked);
	}

	function focusEdge(t: GraphTxn) {
		if (!cy) return;
		const e = cy.getElementById(`${t.from_account}>${t.to_account}`);
		cy.elements().unselect();
		e.select();
		e.connectedNodes().select();
		cy.animate({ center: { eles: e }, duration: 300 });
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

	$effect(() => {
		void focus;
		recolor();
	});

	onMount(() => {
		if (!data.network || !container) return;
		let destroyed = false;
		let dash: ReturnType<typeof setInterval> | undefined;
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
						'background-color': '#ffffff', width: 'data(size)', height: 'data(size)', label: 'data(label)',
						'font-size': 9, 'font-family': 'Inter, "IBM Plex Sans Thai", sans-serif', color: '#4d506e', 'text-valign': 'bottom',
						'text-margin-y': 5, 'text-wrap': 'wrap', 'text-max-width': '110px', 'text-background-color': '#ffffff',
						'text-background-opacity': 0.75, 'text-background-padding': '2px', 'text-background-shape': 'roundrectangle',
						'border-width': 2.5, 'border-color': '#9ca7de', 'transition-property': 'opacity', 'transition-duration': 200 } },
					{ selector: 'node.risk-med', style: { 'background-color': '#fde7d6', 'border-color': RISK_MED } },
					{ selector: 'node.risk-high', style: { 'background-color': '#fbd3b8', 'border-color': RISK_HIGH } },
					{ selector: 'node.merchant', style: { 'background-color': '#05060b', 'border-color': '#05060b', color: '#05060b', 'font-weight': 600 } },
					{ selector: 'node.seed', style: { 'border-color': '#05060b', 'border-width': 3.5, 'font-weight': 700, color: '#05060b' } },
					{ selector: 'node.frozen', style: { 'border-color': '#6c72ac', 'border-width': 5, 'border-style': 'double' } },
					{ selector: 'node.victim', style: { 'background-color': '#6c72ac', 'border-color': '#fff', 'border-width': 4, 'font-weight': 700, color: '#05060b' } },
					{ selector: 'node.holding', style: { 'border-color': RISK_HIGH, 'border-width': 5, 'font-weight': 700, color: RISK_HIGH } },
					{ selector: 'node.group', style: {
						'background-color': '#ecf0f8', 'background-opacity': 0.5, 'border-color': '#9ca7de', 'border-width': 1.5,
						'border-style': 'dashed', shape: 'round-rectangle', label: 'data(label)', 'text-valign': 'top',
						'font-size': 10, 'font-weight': 600, color: '#6c72ac', padding: '22px', 'text-background-opacity': 0 } },
					{ selector: 'node:selected', style: { 'overlay-color': '#6c72ac', 'overlay-opacity': 0.18, 'overlay-padding': 7 } },
					{ selector: 'edge', style: {
						width: 'data(width)', 'line-color': '#c3c9ea', 'target-arrow-color': '#c3c9ea', 'target-arrow-shape': 'triangle',
						'arrow-scale': 0.7, 'curve-style': 'bezier', opacity: 0.8, 'line-style': 'dashed', 'line-dash-pattern': [6, 4] } },
					{ selector: 'edge.in', style: { 'line-color': IN, 'target-arrow-color': IN, opacity: 0.9 } },
					{ selector: 'edge.out', style: { 'line-color': OUT, 'target-arrow-color': OUT, opacity: 0.9 } },
					{ selector: 'edge.traced', style: { 'line-color': RISK_HIGH, 'target-arrow-color': RISK_HIGH, opacity: 1, 'z-index': 10, 'line-style': 'solid' } },
					{ selector: 'edge:selected', style: { width: 4, opacity: 1, 'z-index': 20 } },
					{ selector: '.faded', style: { display: 'none' } },
					{ selector: '.future', style: { display: 'none' } }
				]
			});
			win = { start: +new Date(data.network!.window.start), end: +new Date(data.network!.window.end) };
			at = win.end;
			addNetwork(data.network!, true);
			cy.on('tap', 'node', (e) => {
				const n = e.target;
				detailsOpen = true;
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
			cy.on('zoom', () => (zoomPct = Math.round(cy!.zoom() * 100)));
			if (data.trace) {
				cy.one('layoutstop', () => showTrace(data.trace!));
			}
			layout({ randomize: true, animate: false });
			// marching dashes on the coloured flows
			let offset = 0;
			dash = setInterval(() => {
				offset = (offset - 1) % 100;
				cy?.edges('.in, .out').style('line-dash-offset', offset);
			}, 70);
		})();
		return () => {
			destroyed = true;
			clearInterval(timer);
			clearInterval(dash);
			cy?.destroy();
		};
	});

	// ---- panels: overview + transfers table (recomputed when the graph or the slider changes)
	const visibleTxns = $derived.by(() => {
		void version;
		return [...txns.values()].filter((t) => +new Date(t.ts) <= at);
	});
	const overview = $derived.by(() => {
		void version;
		const ids = new Set(visibleTxns.flatMap((t) => [t.from_account, t.to_account]));
		return {
			volume: visibleTxns.reduce((s, t) => s + t.amount_satang, 0),
			transfers: visibleTxns.length,
			accounts: ids.size,
			flagged: [...ids].filter((i) => (nodes.get(i)?.risk ?? 0) >= 70).length
		};
	});
	const rows = $derived.by(() => {
		const dir = (t: GraphTxn) =>
			focus.has(t.to_account) && focus.has(t.from_account) ? 'within' : focus.has(t.to_account) ? 'in' : focus.has(t.from_account) ? 'out' : 'other';
		return visibleTxns
			.filter((t) => t.amount_satang >= minBaht * 100)
			.filter((t) => tab === 'all' || dir(t) === tab)
			.sort((a, b) => +new Date(b.ts) - +new Date(a.ts))
			.slice(0, 300)
			.map((t) => ({ ...t, dir: dir(t) }));
	});

	const fmtTime = (ms: number) =>
		new Date(ms).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Bangkok' });
	const ago = (ts: string) => {
		const m = Math.round((at - +new Date(ts)) / 60_000);
		return m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
	};
	const dot = (id: string) => {
		const n = nodes.get(id);
		return n?.type === 'merchant' ? 'bg-ink' : (n?.risk ?? 0) >= 90 ? 'bg-alert' : (n?.risk ?? 0) >= 70 ? 'bg-[#f4a46a]' : 'bg-haze';
	};
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
	<section class="relative -mx-2 h-full min-h-[480px] overflow-hidden rounded-3xl bg-white/60 shadow-card sm:-mx-4">
		<div bind:this={container} class="h-full w-full" data-testid="graph"></div>

		<!-- left: overview -->
		<aside class="absolute top-3 left-3 w-64 max-w-[calc(100%-1.5rem)] rounded-3xl bg-white/95 p-4 shadow-card backdrop-blur">
			<div class="flex items-center justify-between">
				<p class="font-semibold">{caseId ? 'Case network' : 'Account network'}</p>
				{#if caseId}<a href="/cases/{caseId}" class="text-xs text-accent hover:underline">case →</a>{/if}
			</div>
			<p class="mt-3 text-[10px] font-medium tracking-wider text-ink-muted uppercase">Overview</p>
			<dl class="mt-1.5 space-y-1.5 text-xs">
				<div class="flex justify-between"><dt class="text-ink-muted">Transfer volume</dt><dd class="font-semibold tabular-nums">{thb(overview.volume)}</dd></div>
				<div class="flex justify-between"><dt class="text-ink-muted">Transfers</dt><dd class="font-semibold tabular-nums">{overview.transfers.toLocaleString()}</dd></div>
				<div class="flex justify-between"><dt class="text-ink-muted">Accounts</dt><dd class="font-semibold tabular-nums">{overview.accounts}</dd></div>
				<div class="flex justify-between"><dt class="text-ink-muted">Flagged</dt><dd class="font-semibold text-alert tabular-nums">{overview.flagged}</dd></div>
				<div class="flex justify-between"><dt class="text-ink-muted">Networks</dt><dd class="font-semibold tabular-nums">{data.network.groups.length}</dd></div>
			</dl>
			<p class="mt-3 text-[10px] font-medium tracking-wider text-ink-muted uppercase">Nodes · {data.network.seeds.length}</p>
			<div class="mt-1.5 flex max-h-40 flex-wrap gap-1.5 overflow-auto">
				{#each data.network.seeds as s (s)}
					<a href="/accounts/{s}" class="flex items-center gap-1.5 rounded-full bg-mist px-2 py-1 text-[11px] hover:bg-haze/40" title={s}>
						<span class="size-2 rounded-full {dot(s)}"></span>{nodeName(s)}
					</a>
				{/each}
			</div>
			<div class="mt-3 flex items-center gap-3 text-[10px] text-ink-muted">
				<span class="flex items-center gap-1"><span class="h-0.5 w-4 border-t-2 border-dashed border-[#16a34a]"></span>in</span>
				<span class="flex items-center gap-1"><span class="h-0.5 w-4 border-t-2 border-dashed border-[#e5484d]"></span>out</span>
				<span class="flex items-center gap-1"><span class="size-2 rounded-full bg-alert"></span>flagged</span>
				<span class="flex items-center gap-1"><span class="size-2 rounded-full bg-ink"></span>merchant</span>
			</div>
		</aside>

		<!-- right: transfers + details -->
		<aside class="absolute top-3 right-3 bottom-24 flex w-[26rem] max-w-[calc(100%-1.5rem)] flex-col gap-2">
			<div class="flex min-h-0 flex-1 flex-col rounded-3xl bg-white/95 shadow-card backdrop-blur">
				<div class="flex items-center gap-1 border-b border-mist px-3 pt-3 pb-2 text-[11px] font-medium">
					{#each [['all', 'All transfers'], ['in', 'Incoming'], ['out', 'Outgoing'], ['within', 'Within']] as [k, label] (k)}
						<button onclick={() => (tab = k as typeof tab)} class="rounded-full px-2.5 py-1 {tab === k ? 'bg-ink text-white' : 'text-ink-muted hover:bg-mist'}">{label}</button>
					{/each}
					<label class="ml-auto flex items-center gap-1 rounded-full bg-mist px-2 py-1 text-ink-muted">
						฿ ≥ <input type="number" min="0" step="100" bind:value={minBaht} class="w-14 bg-transparent text-ink outline-none" />
					</label>
				</div>
				<p class="px-4 pt-1.5 text-[10px] text-ink-muted">Relative to {selected ? nodeName(selected.id) : 'the network accounts'} · {rows.length}{rows.length === 300 ? '+' : ''} shown</p>
				<div class="min-h-0 flex-1 overflow-auto px-2 pb-2">
					<table class="w-full text-left text-[11px]">
						<thead class="sticky top-0 bg-white text-ink-muted">
							<tr><th class="px-2 py-1.5 font-medium">Time</th><th class="font-medium">From</th><th class="font-medium">To</th><th class="px-2 text-right font-medium">Value</th></tr>
						</thead>
						<tbody>
							{#each rows as t (t.id)}
								<tr onclick={() => focusEdge(t)} class="cursor-pointer border-t border-mist hover:bg-mist/60" title={t.id}>
									<td class="px-2 py-1.5 text-ink-muted tabular-nums">{ago(t.ts)}</td>
									<td class="max-w-28 truncate"><span class="mr-1 inline-block size-1.5 rounded-full {dot(t.from_account)}"></span>{nodeName(t.from_account)}</td>
									<td class="max-w-28 truncate"><span class="mr-1 inline-block size-1.5 rounded-full {dot(t.to_account)}"></span>{nodeName(t.to_account)}</td>
									<td class="px-2 text-right font-medium tabular-nums {t.dir === 'in' ? 'text-[#16a34a]' : t.dir === 'out' ? 'text-[#e5484d]' : ''}">{thb(t.amount_satang)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<div class="rounded-3xl bg-white/95 shadow-card backdrop-blur {detailsOpen && (trace || selected || selectedGroup) ? 'max-h-[48%] overflow-y-auto' : ''}">
				<button onclick={() => (detailsOpen = !detailsOpen)} class="flex w-full items-center justify-between px-4 py-2.5 text-[11px] font-medium tracking-wider text-ink-muted uppercase">
					Details <ChevronDown size={14} class="transition {detailsOpen ? 'rotate-180' : ''}" />
				</button>
				{#if detailsOpen && (trace || selected || selectedGroup)}
					<div class="space-y-3 px-4 pb-4">
						{#if selected}
							{@const n = selected}
							<div class="flex items-start justify-between gap-2">
								<div>
									<p class="font-semibold">{n.name}</p>
									<p class="text-xs text-ink-muted">{n.id} · {n.type} · KYC {n.kyc_level}</p>
								</div>
								<button onclick={() => (selected = null)} class="text-ink-muted"><X size={16} /></button>
							</div>
							<div class="flex flex-wrap gap-1.5 text-xs">
								{#if n.risk}<span class="rounded-full bg-alert/10 px-2.5 py-1 font-semibold text-alert">risk {n.risk}</span>{/if}
								<span class="rounded-full px-2.5 py-1 {n.status === 'frozen' ? 'bg-accent text-white' : 'bg-mist'}">{n.status}</span>
							</div>
							<dl class="grid grid-cols-2 gap-2 text-sm">
								<div class="rounded-2xl bg-mist p-3"><dt class="text-xs text-ink-muted">In (window)</dt><dd class="font-semibold text-[#16a34a] tabular-nums">{thb(n.in_satang)}</dd></div>
								<div class="rounded-2xl bg-mist p-3"><dt class="text-xs text-ink-muted">Out (window)</dt><dd class="font-semibold text-[#e5484d] tabular-nums">{thb(n.out_satang)}</dd></div>
							</dl>
							<div class="flex gap-2">
								<button onclick={() => expand(n.id)} disabled={busy} class="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-ink py-2 text-xs font-medium text-white disabled:opacity-50">
									<Plus size={14} /> Expand 1 hop
								</button>
								<a href="/accounts/{n.id}" class="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-mist py-2 text-xs font-medium"><ExternalLink size={13} /> Entity page</a>
							</div>
							{#if !n.risk && n.type !== 'merchant'}
								<button onclick={() => runTrace(n.id)} disabled={busy} class="w-full rounded-full bg-white py-2 text-xs font-medium ring-1 ring-ink/15">Trace from this account as victim</button>
							{/if}
							{#each n.cases as c (c)}
								<a href="/cases/{c}" class="text-xs font-medium text-accent hover:underline">Open case →</a>
							{/each}
						{:else if selectedGroup}
							{@const g = selectedGroup}
							<p class="font-semibold">Network of {g.members.length} accounts</p>
							<p class="text-sm text-ink-muted">{g.flagged} flagged by the scorer. Flagged accounts connected by money flow in this window, plus pass-through accounts between them.</p>
							{#if g.case_id}
								<a href="/cases/{g.case_id}" class="block rounded-full bg-ink py-2 text-center text-xs font-medium text-white">Open network case</a>
							{/if}
							<ul class="space-y-1 text-xs">
								{#each g.members as m (m)}<li class="flex justify-between"><a href="/accounts/{m}" class="hover:underline">{nodeName(m)}</a><span class="text-ink-muted">{m}</span></li>{/each}
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
											{c.name} · {thb(c.paid_satang)}
										</button>
									{/each}
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		</aside>

		{#if message || data.error}
			<p class="absolute top-3 left-1/2 -translate-x-1/2 rounded-full bg-ink px-3 py-1 text-xs text-white">{message || data.error}</p>
		{/if}

		<!-- bottom: zoom + toolbar + time slider -->
		<div class="absolute inset-x-3 bottom-3 flex flex-wrap items-center gap-2">
			<div class="flex items-center gap-1 rounded-full bg-white/95 px-2 py-1.5 text-xs shadow-card">
				<button onclick={() => zoomBy(0.8)} class="grid size-7 place-items-center rounded-full hover:bg-mist" title="Zoom out"><Minus size={13} /></button>
				<span class="w-10 text-center tabular-nums">{zoomPct}%</span>
				<button onclick={() => zoomBy(1.25)} class="grid size-7 place-items-center rounded-full hover:bg-mist" title="Zoom in"><Plus size={13} /></button>
				<button onclick={() => cy?.fit(undefined, 60)} class="grid size-7 place-items-center rounded-full hover:bg-mist" title="Fit to screen"><Maximize size={13} /></button>
			</div>
			<div class="flex items-center gap-1 rounded-full bg-white/95 px-2 py-1.5 shadow-card">
				<button onclick={toggleLock} class="grid size-7 place-items-center rounded-full hover:bg-mist" title={locked ? 'Unlock nodes' : 'Lock nodes'}>
					{#if locked}<Lock size={13} />{:else}<LockOpen size={13} />{/if}
				</button>
				<button onclick={() => layout({ randomize: true })} class="grid size-7 place-items-center rounded-full hover:bg-mist" title="Re-layout"><Shuffle size={13} /></button>
				<button onclick={toggleGroups} class="flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium {showGroups ? 'bg-mist' : ''}"><Boxes size={13} /> Networks</button>
				<button onclick={() => (trace ? clearTrace() : runTrace())} disabled={busy}
					class="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-white {trace ? 'bg-alert' : 'bg-ink'}">
					{#if trace}<X size={13} /> Exit trace{:else}<Crosshair size={13} /> Trace from victim{/if}
				</button>
			</div>
			<div class="flex min-w-64 flex-1 items-center gap-3 rounded-full bg-white/95 py-1.5 pr-4 pl-1.5 shadow-card">
				<button onclick={play} class="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-white" title={playing ? 'Pause' : 'Replay money flow'}>
					{#if playing}<Pause size={13} />{:else}<Play size={13} />{/if}
				</button>
				<input type="range" min={win.start} max={win.end} step={60_000} bind:value={at} oninput={applyTime} class="flex-1 accent-[#ec630d]" aria-label="Time" />
				<span class="w-28 shrink-0 text-right text-xs font-medium tabular-nums">{fmtTime(at)}</span>
			</div>
		</div>
	</section>
{/if}
