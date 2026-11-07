<script lang="ts">
	import { page } from '$app/state';
	import { ROLE_LABEL } from '#lib/roles.ts';
	import {
		ArrowRightLeft,
		BellRing,
		BrainCircuit,
		FolderSearch,
		LayoutDashboard,
		LogOut,
		Network,
		Receipt,
		ScrollText,
		ShieldCheck
	} from '@lucide/svelte';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	// Pages arrive milestone by milestone; links without a page yet are shown disabled.
	const nav = [
		{ href: '/', label: 'Command Center', icon: LayoutDashboard, ready: true },
		{ href: '/alerts', label: 'Alert Queue', icon: BellRing, ready: true },
		{ href: '/cases', label: 'Cases', icon: FolderSearch, ready: true },
		{ href: '/graph', label: 'Graph Explorer', icon: Network, ready: true },
		{ href: '/recon', label: 'Reconciliation', icon: ArrowRightLeft, ready: true },
		{ href: '/follow-ups', label: 'Follow-ups', icon: Receipt, ready: true },
		{ href: '/tuning', label: 'Model Tuning', icon: BrainCircuit, ready: true },
		{ href: '/audit', label: 'Audit Log', icon: ScrollText, ready: false }
	];
</script>

<div class="flex h-dvh gap-4 overflow-hidden p-3 sm:p-5">
	<nav class="hidden flex-col items-center gap-2 pt-2 sm:flex" aria-label="Main">
		<span class="mb-4 grid size-10 place-items-center rounded-full bg-ink text-white"><ShieldCheck size={18} /></span>
		{#each nav as item (item.href)}
			{@const active = item.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(item.href)}
			<a
				href={item.ready ? item.href : undefined}
				aria-disabled={!item.ready}
				title={item.label}
				class="grid size-10 place-items-center rounded-full transition
					{active ? 'bg-white text-ink shadow-card' : 'text-ink-muted hover:bg-white/60'}
					{item.ready ? '' : 'pointer-events-none opacity-40'}"
			>
				<item.icon size={18} />
			</a>
		{/each}
		<form method="POST" action="/logout" class="mt-auto">
			<button title="Sign out" class="grid size-10 place-items-center rounded-full text-ink-muted hover:bg-white/60">
				<LogOut size={18} />
			</button>
		</form>
	</nav>

	<div class="glass flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-3xl shadow-panel">
		<header class="flex shrink-0 items-center justify-between gap-4 px-5 py-4 sm:px-8">
			<div class="flex items-center gap-2 rounded-full bg-white px-3 py-1.5 text-xs font-medium shadow-card">
				<ShieldCheck size={14} class="text-accent" /> Zentry · Demo e-wallet
			</div>
			<p class="hidden text-sm font-medium text-ink-muted md:block">
				{nav.find((n) => (n.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(n.href)))?.label ?? ''}
			</p>
			<div class="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white">
				{data.role ? ROLE_LABEL[data.role] : 'No role'}
			</div>
		</header>
		<main class="min-h-0 flex-1 overflow-y-auto px-5 pb-6 sm:px-8">
			{@render children()}
		</main>
	</div>
</div>
