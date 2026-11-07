<script lang="ts">
	import { onMount } from 'svelte';
	import {
		ArrowRight,
		ArrowRightLeft,
		BadgeCheck,
		BellRing,
		BrainCircuit,
		Check,
		EyeOff,
		FileCheck2,
		Lock,
		Mail,
		Play,
		Radio,
		ShieldCheck,
		Sparkles,
		UserCheck
	} from '@lucide/svelte';
	import { LOGOS } from '#lib/landing/logos.ts';

	const steps = [
		{ n: '01', title: 'Stream', icon: Radio, body: 'Every e-wallet transfer flows in the moment it happens. Nothing is batched overnight.' },
		{ n: '02', title: 'Score', icon: BellRing, body: 'Our AI model and five plain-language rules flag risky transfers in milliseconds.' },
		{ n: '03', title: 'Investigate', icon: BrainCircuit, body: 'An AI agent follows the money and writes a report that cites every transaction.' },
		{ n: '04', title: 'Decide', icon: UserCheck, body: 'People freeze, report, confirm and approve. Every decision is recorded.' }
	];

	const rules = [
		{ name: 'Money passes straight through', hit: true },
		{ name: 'Many senders, one collector', hit: true },
		{ name: 'Brand-new account, strangers paying in', hit: true },
		{ name: 'Amounts split to stay under limits', hit: false },
		{ name: 'Dormant account wakes up', hit: false }
	];

	const breaks = [
		{ label: 'Fee', n: 10 },
		{ label: 'Timing', n: 10 },
		{ label: 'Duplicate', n: 10 },
		{ label: 'Wrong amount', n: 10 },
		{ label: 'Missing in bank', n: 10 },
		{ label: 'Missing in ledger', n: 10 }
	];

	const evidence = [
		'Account history reviewed',
		'Money traced three hops out',
		'Shared phone found across 6 accounts',
		'142 transactions cited · 142 verified'
	];

	const guardrails = [
		'AI agents can look, not touch. They only propose actions',
		'Reports citing a transaction that does not exist never reach an analyst',
		'Freezes, regulator reports, outbound messages and model updates wait for a person',
		'Every AI prompt, answer and human decision is kept in the audit log',
		'Full names stay hidden unless someone states a reason, and that is recorded',
		'Money is counted to the last satang, never rounded'
	];

	// hero: a synthetic live feed
	const people = ['Somying Sd****', 'Anucha Ka****', 'Wilai Sr****', 'Jiraporn In****', 'Thanapol Ja****', 'Ekachai Bo****', 'Prasert Me****', 'Napat Ch****'];
	type Tx = { id: number; from: string; to: string; amount: string; score: number };
	let seq = 0;
	function nextTx(): Tx {
		const score = Math.random() < 0.35 ? 90 + Math.floor(Math.random() * 10) : 5 + Math.floor(Math.random() * 40);
		const baht = score > 89 ? 8_000 + Math.random() * 60_000 : 50 + Math.random() * 3_000;
		const from = Math.floor(Math.random() * people.length);
		const to = (from + 1 + Math.floor(Math.random() * (people.length - 1))) % people.length; // never the sender
		return {
			id: seq++,
			from: people[from],
			to: people[to],
			amount: '฿' + baht.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
			score
		};
	}
	let feed = $state<Tx[]>([nextTx(), nextTx(), nextTx(), nextTx()]);

	// hero: the agent report types itself out
	const REPORT =
		'A0004094 sent ฿28,774.05 to A0006872 (TX00120342) and ฿297,836.88 to A0011519 (TX00120956) from the same phone. Within two hours the money was spread across 18 wallets and spent at gold and phone shops.';
	let typed = $state(0);

	let video: HTMLVideoElement | undefined = $state();

	onMount(() => {
		if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
			typed = REPORT.length;
			return;
		}
		const feedTimer = setInterval(() => (feed = [nextTx(), ...feed].slice(0, 4)), 1600);
		const typeTimer = setInterval(() => {
			typed = typed >= REPORT.length + 60 ? 0 : typed + 2; // pause at the end, then start over
		}, 45);
		// play the tour only while it is on screen
		const io = new IntersectionObserver(([e]) => (e.isIntersecting ? video?.play().catch(() => {}) : video?.pause()), {
			threshold: 0.4
		});
		if (video) io.observe(video);
		return () => {
			clearInterval(feedTimer);
			clearInterval(typeTimer);
			io.disconnect();
		};
	});

	/** Fade-and-rise when the element scrolls into view. */
	function reveal(node: HTMLElement, delay = 0) {
		node.style.setProperty('--d', `${delay}ms`);
		node.classList.add('reveal');
		const io = new IntersectionObserver(
			([e]) => {
				if (e.isIntersecting) {
					node.classList.add('in');
					io.disconnect();
				}
			},
			{ threshold: 0.15 }
		);
		io.observe(node);
		return { destroy: () => io.disconnect() };
	}

	// small static graph for the capability card
	const ring = [
		{ x: 150, y: 90, r: 14, c: '#EC630D' },
		{ x: 70, y: 40, r: 7, c: '#6C72AC' },
		{ x: 60, y: 120, r: 7, c: '#6C72AC' },
		{ x: 95, y: 165, r: 7, c: '#6C72AC' },
		{ x: 235, y: 45, r: 9, c: '#EC630D' },
		{ x: 250, y: 140, r: 9, c: '#EC630D' },
		{ x: 315, y: 90, r: 11, c: '#05060B' }
	];
	const edges = [
		[1, 0, 'in'],
		[2, 0, 'in'],
		[3, 0, 'in'],
		[0, 4, 'out'],
		[0, 5, 'out'],
		[4, 6, 'out'],
		[5, 6, 'out']
	] as const;
</script>

<svelte:head>
	<title>Zentry: follow the money, close the books</title>
	<meta
		name="description"
		content="Zentry is an AI desk for Thai e-wallets: catch money-mule rings in real time, investigate with cited evidence, reconcile settlements and chase payments, with people approving every action."
	/>
</svelte:head>

<div class="relative min-h-dvh overflow-x-clip">
	<!-- drifting background glow -->
	<div class="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[900px]" aria-hidden="true">
		<div class="blob top-[-120px] left-[-80px] size-[460px] bg-haze/60"></div>
		<div class="blob blob-2 top-[120px] right-[-120px] size-[520px] bg-accent/30"></div>
		<div class="blob blob-3 top-[520px] left-[30%] size-[380px] bg-alert/10"></div>
	</div>

	<!-- nav -->
	<header class="sticky top-0 z-30 border-b border-white/60 bg-mist/70 backdrop-blur-xl">
		<nav class="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
			<a href="/welcome" class="flex items-center gap-2 font-semibold">
				<span class="grid size-8 place-items-center rounded-full bg-ink text-white"><ShieldCheck size={16} /></span>
				Zentry
			</a>
			<div class="hidden items-center gap-6 text-sm text-ink-muted md:flex">
				<a href="#how" class="hover:text-ink">How it works</a>
				<a href="#capabilities" class="hover:text-ink">Capabilities</a>
				<a href="#demo" class="hover:text-ink">Demo</a>
				<a href="#guardrails" class="hover:text-ink">Guardrails</a>
			</div>
			<a href="/login" class="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-sm font-medium text-white transition hover:scale-[1.03]">
				Open the desk <ArrowRight size={14} />
			</a>
		</nav>
	</header>

	<!-- hero -->
	<section class="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-14 pb-12 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
		<div use:reveal>
			<p class="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-xs font-semibold tracking-[0.14em] text-accent shadow-card">
				<span class="live-dot"></span> FINANCIAL CRIME · PAYMENT OPS
			</p>
			<h1 class="mt-5 text-4xl leading-[1.05] font-semibold tracking-tight sm:text-6xl">
				Follow the money.<br /><span class="shine">Close the books.</span>
			</h1>
			<p class="mt-5 max-w-xl text-lg text-ink-muted">
				One AI desk for Thai e-wallets. Catch money-mule rings as they form, get investigations with evidence you can check,
				reconcile settlements and chase payments. People stay in charge of every action.
			</p>
			<div class="mt-8 flex flex-wrap items-center gap-3">
				<a href="/login" class="group flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-medium text-white shadow-panel transition hover:scale-[1.03]">
					Try the live demo <ArrowRight size={16} class="transition group-hover:translate-x-0.5" />
				</a>
				<a href="#demo" class="flex items-center gap-2 rounded-full bg-white px-5 py-3 text-sm font-medium shadow-card transition hover:scale-[1.03]">
					<Play size={15} class="text-accent" /> Watch the tour
				</a>
			</div>
			<p class="mt-5 text-xs text-ink-muted">Synthetic data only. Not connected to any real bank or regulator.</p>
		</div>

		<!-- hero visual: live feed + agent report -->
		<div class="relative" use:reveal={150}>
			<div class="glass rounded-3xl p-4 shadow-panel sm:p-5">
				<div class="flex items-center justify-between">
					<p class="flex items-center gap-2 text-sm font-semibold"><span class="live-dot"></span> Live transfers</p>
					<span class="text-xs text-ink-muted">scored by our AI</span>
				</div>
				<ul class="mt-3 space-y-2">
					{#each feed as tx (tx.id)}
						<li class="feed-row flex items-center justify-between gap-3 rounded-2xl bg-white px-3 py-2.5 shadow-card">
							<div class="min-w-0">
								<p class="truncate text-sm font-medium">{tx.from} <span class="text-ink-muted">→</span> {tx.to}</p>
								<p class="text-xs text-ink-muted">{tx.amount}</p>
							</div>
							{#if tx.score > 89}
								<span class="shrink-0 rounded-full bg-alert px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-white">Flagged · {tx.score}</span>
							{:else}
								<span class="shrink-0 rounded-full bg-mist px-2.5 py-1 text-xs whitespace-nowrap text-ink-muted">Clear · {tx.score}</span>
							{/if}
						</li>
					{/each}
				</ul>
				<div class="mt-3 rounded-2xl bg-ink p-4 text-white">
					<p class="flex items-center gap-1.5 text-xs font-medium text-haze"><Sparkles size={13} /> AI agent · investigating</p>
					<p class="mt-2 min-h-[6.5rem] text-sm leading-relaxed text-white/90">
						{REPORT.slice(0, typed)}<span class="caret">▍</span>
					</p>
				</div>
			</div>
			<div class="float absolute -bottom-5 left-3 flex items-center gap-2 rounded-full bg-white px-4 py-2 text-xs font-medium shadow-panel sm:-left-8">
				<Lock size={13} class="text-alert" /> Freeze 6 accounts? <span class="text-ink-muted">awaits analyst</span>
			</div>
			<div class="float float-2 absolute -top-4 right-3 flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium shadow-panel sm:-right-6">
				<BadgeCheck size={13} class="text-emerald-600" /> 142 / 142 ids verified
			</div>
		</div>
	</section>

	<!-- powered by: logo marquee -->
	<section class="py-10" aria-label="Powered by">
		<p class="text-center text-xs font-semibold tracking-[0.18em] text-ink-muted">POWERED BY</p>
		<div class="marquee mt-5">
			<div class="marquee-track">
				<!-- four copies; the track scrolls by half, so it loops seamlessly even on wide screens -->
				{#each [0, 1, 2, 3] as copy (copy)}
					{#each LOGOS as logo (logo.name + copy)}
						<span class="flex shrink-0 items-center gap-2.5 rounded-full bg-white/80 px-5 py-2.5 shadow-card" aria-hidden={copy > 0}>
							<svg viewBox="0 0 24 24" class="size-5" fill={logo.color} aria-hidden="true"><path d={logo.path} /></svg>
							<span class="text-sm font-semibold">{logo.name}</span>
						</span>
					{/each}
				{/each}
			</div>
		</div>
	</section>

	<!-- how it works -->
	<section id="how" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div use:reveal>
			<p class="text-xs font-semibold tracking-[0.18em] text-accent">HOW IT WORKS</p>
			<h2 class="mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">From transfer to decision in four steps.</h2>
		</div>
		<div class="mt-8 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
			{#each steps as s, i (s.n)}
				<div use:reveal={i * 100} class="glass lift rounded-3xl p-5 shadow-card">
					<div class="flex items-center justify-between">
						<span class="text-sm font-semibold text-accent">{s.n}</span>
						<span class="grid size-9 place-items-center rounded-full bg-ink text-white"><s.icon size={16} /></span>
					</div>
					<h3 class="mt-6 text-lg font-semibold">{s.title}</h3>
					<p class="mt-1.5 text-sm text-ink-muted">{s.body}</p>
				</div>
			{/each}
		</div>
	</section>

	<!-- capabilities -->
	<section id="capabilities" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div use:reveal>
			<p class="text-xs font-semibold tracking-[0.18em] text-accent">DETECT · INVESTIGATE · RECONCILE · FOLLOW UP</p>
			<h2 class="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Six capabilities. One desk. AI that shows its work.</h2>
		</div>

		<div class="mt-10 space-y-6">
			<!-- 01 detection -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">01 · REAL-TIME DETECTION</p>
					<h3 class="mt-2 text-2xl font-semibold">Flags you can explain.</h3>
					<p class="mt-3 text-ink-muted">
						Our AI model scores every transfer as it happens. Five plain-language rules name the pattern, so an analyst
						knows why something was flagged before opening it.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between">
						<p class="text-sm font-medium">TX00120956 · ฿297,836.88</p>
						<span class="pulse rounded-full bg-alert px-2.5 py-1 text-xs font-semibold text-white">risk 97</span>
					</div>
					<div class="mt-4 space-y-2">
						{#each rules as r (r.name)}
							<div class="flex items-center justify-between gap-3 rounded-xl bg-mist/70 px-3 py-2 text-sm">
								<span>{r.name}</span>
								{#if r.hit}
									<span class="text-xs font-semibold text-alert">MATCH</span>
								{:else}
									<span class="text-xs text-ink-muted">clear</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			</article>

			<!-- 02 agent -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">02 · AI INVESTIGATIONS</p>
					<h3 class="mt-2 text-2xl font-semibold">No transaction, no claim.</h3>
					<p class="mt-3 text-ink-muted">
						The AI agent can look but not touch. It reads account history, traces where the money went and writes a case
						report. Before anyone sees it, every transaction it mentions is checked against the ledger.
					</p>
				</div>
				<div class="rounded-3xl bg-ink p-5 text-white shadow-panel lg:order-1">
					<p class="flex items-center gap-1.5 text-xs font-medium text-haze"><Sparkles size={13} /> Evidence check</p>
					<ul class="mt-3 space-y-2.5">
						{#each evidence as e, i (e)}
							<li use:reveal={200 + i * 180} class="flex items-center gap-2.5 text-sm text-white/90">
								<span class="grid size-5 place-items-center rounded-full bg-emerald-400/20 text-emerald-300"><Check size={12} /></span>
								{e}
							</li>
						{/each}
					</ul>
					<p class="mt-4 inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-3 py-1 text-xs text-emerald-300">
						<BadgeCheck size={14} /> Report verified · sent to analyst
					</p>
				</div>
			</article>

			<!-- 03 graph -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">03 · FOLLOW THE MONEY</p>
					<h3 class="mt-2 text-2xl font-semibold">See the ring, not just the row.</h3>
					<p class="mt-3 text-ink-muted">
						Money in shows green and money out shows red. Scrub through time, spot whole networks, and trace from a victim
						to see how much can still be recovered.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-4 shadow-card">
					<svg viewBox="0 0 380 210" class="w-full" role="img" aria-label="Mule ring graph">
						{#each edges as [a, b, dir] (`${a}-${b}`)}
							<line
								x1={ring[a].x}
								y1={ring[a].y}
								x2={ring[b].x}
								y2={ring[b].y}
								stroke={dir === 'in' ? '#16a34a' : '#dc2626'}
								stroke-width="1.6"
								stroke-dasharray="5 4"
								class="flow"
							/>
						{/each}
						<circle cx="150" cy="90" r="14" fill="#EC630D" class="ripple" />
						{#each ring as n, i (i)}
							<circle cx={n.x} cy={n.y} r={n.r} fill={n.c} stroke="white" stroke-width="2" />
						{/each}
						<text x="315" y="120" text-anchor="middle" font-size="10" fill="#4D506E">Gold shop</text>
						<text x="150" y="122" text-anchor="middle" font-size="10" fill="#4D506E">collector</text>
					</svg>
				</div>
			</article>

			<!-- 04 recon -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">04 · RECONCILIATION</p>
					<h3 class="mt-2 text-2xl font-semibold">The books match, or you know why.</h3>
					<p class="mt-3 text-ink-muted">
						Bank and payment-gateway files are matched against the ledger automatically. Every mismatch gets a type, a
						plain explanation and a ready-to-post journal entry for finance to confirm.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card lg:order-1">
					<div class="flex items-end justify-between">
						<div>
							<p class="text-xs text-ink-muted">Matched automatically</p>
							<p class="text-3xl font-semibold">99.93%</p>
						</div>
						<span class="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">60 breaks explained</span>
					</div>
					<div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
						{#each breaks as b, i (b.label)}
							<div use:reveal={i * 70} class="rounded-xl bg-mist/70 px-3 py-2">
								<p class="text-[11px] text-ink-muted">{b.label}</p>
								<p class="font-semibold text-alert">{b.n}</p>
							</div>
						{/each}
					</div>
					<div class="mt-3 rounded-xl border border-mist px-3 py-2 text-xs">
						<div class="flex justify-between"><span>Dr Settlement clearing</span><span>฿473.93</span></div>
						<div class="flex justify-between text-ink-muted"><span>Cr Suspense</span><span>฿473.93</span></div>
					</div>
				</div>
			</article>

			<!-- 05 follow-ups -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">05 · PAYMENT FOLLOW-UPS</p>
					<h3 class="mt-2 text-2xl font-semibold">Polite first. Firm when needed.</h3>
					<p class="mt-3 text-ink-muted">
						AI drafts reminders in Thai and English, gets firmer step by step, and reads replies for promised pay dates.
						When a fraud case closes, victims get refund updates too. Nothing is sent without approval.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between text-xs text-ink-muted">
						<span class="flex items-center gap-1.5"><Mail size={13} /> Draft · friendly reminder</span>
						<span>due 21 Nov</span>
					</div>
					<p class="mt-3 text-sm">เรียน ร้านทองเยาวราช กรุณาตรวจสอบค่าธรรมเนียม ฿1,250.00 ที่ยังค้างชำระ…</p>
					<p class="mt-2 text-sm text-ink-muted">Dear Yaowarat Gold Shop, a fee of ฿1,250.00 is still outstanding…</p>
					<div class="mt-4 flex gap-2">
						<span class="flex items-center gap-1 rounded-full bg-ink px-3 py-1.5 text-xs text-white"><Check size={12} /> Approve & send</span>
						<span class="rounded-full bg-mist px-3 py-1.5 text-xs">Reject</span>
					</div>
				</div>
			</article>

			<!-- 06 privacy -->
			<article use:reveal class="lift grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">06 · PRIVACY & LEARNING</p>
					<h3 class="mt-2 text-2xl font-semibold">Private by default. Smarter every week.</h3>
					<p class="mt-3 text-ink-muted">
						Names are masked on screen. Seeing a full name takes the right role and a stated reason, and it is recorded.
						Every analyst decision teaches our model, and a new version goes live only after a person approves it.
					</p>
				</div>
				<div class="space-y-3 lg:order-1">
					<div class="flex items-center justify-between gap-3 rounded-3xl bg-white p-4 shadow-card">
						<div class="flex items-center gap-3">
							<span class="grid size-10 shrink-0 place-items-center rounded-full bg-alert text-white"><EyeOff size={16} /></span>
							<div>
								<p class="font-semibold">Somying Sd****</p>
								<p class="text-xs text-ink-muted">A0006872 · name hidden</p>
							</div>
						</div>
						<span class="rounded-full bg-mist px-3 py-1.5 text-xs whitespace-nowrap">Reveal · reason needed</span>
					</div>
					<div class="flex items-center gap-3 rounded-3xl bg-white p-4 shadow-card">
						<span class="grid size-10 shrink-0 place-items-center rounded-full bg-ink text-white"><BrainCircuit size={16} /></span>
						<div class="min-w-0 flex-1">
							<p class="text-sm font-semibold">New model ready · learned from 1 week of decisions</p>
							<div class="mt-2 h-2 overflow-hidden rounded-full bg-mist"><div class="bar h-full rounded-full bg-accent"></div></div>
						</div>
						<span class="rounded-full bg-ink px-3 py-1.5 text-xs whitespace-nowrap text-white">Approve</span>
					</div>
				</div>
			</article>
		</div>
	</section>

	<!-- demo video -->
	<section id="demo" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div use:reveal class="text-center">
			<p class="text-xs font-semibold tracking-[0.18em] text-accent">PRODUCT TOUR</p>
			<h2 class="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">See a mule ring go from alert to decision.</h2>
		</div>
		<div use:reveal={100} class="relative mt-8">
			<div class="absolute -inset-4 -z-10 rounded-[2.5rem] bg-haze/50 blur-3xl"></div>
			<div class="glass overflow-hidden rounded-[2rem] p-2 shadow-panel sm:p-3">
				<div class="flex items-center gap-1.5 px-3 pb-2 sm:pb-3">
					<span class="size-2.5 rounded-full bg-[#ff5f57]"></span>
					<span class="size-2.5 rounded-full bg-[#febc2e]"></span>
					<span class="size-2.5 rounded-full bg-[#28c840]"></span>
					<span class="ml-3 truncate rounded-full bg-white/80 px-3 py-0.5 text-[11px] text-ink-muted">zentry · command center</span>
				</div>
				<!-- svelte-ignore a11y_media_has_caption -->
				<video
					bind:this={video}
					class="aspect-[16/10] w-full rounded-2xl bg-ink object-cover"
					src="/demo/zentry-demo.mp4"
					poster="/demo/poster.jpg"
					controls
					muted
					loop
					playsinline
					preload="metadata"
				></video>
			</div>
		</div>
	</section>

	<!-- guardrails -->
	<section id="guardrails" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div use:reveal class="grid gap-8 rounded-[2rem] bg-ink p-6 text-white shadow-panel sm:p-10 lg:grid-cols-[1fr_1.3fr]">
			<div>
				<p class="text-xs font-semibold tracking-[0.18em] text-haze">GUARDRAILS</p>
				<h2 class="mt-3 text-3xl font-semibold tracking-tight">AI proposes. People decide.</h2>
				<p class="mt-3 text-white/70">
					Built for regulated work. Every AI agent has a narrow job, its work is checked, and everything it does is on the
					record.
				</p>
			</div>
			<ul class="grid gap-3 sm:grid-cols-2">
				{#each guardrails as g, i (g)}
					<li use:reveal={i * 80} class="flex gap-3 rounded-2xl bg-white/5 p-4 text-sm text-white/85 transition hover:bg-white/10">
						<FileCheck2 size={18} class="mt-0.5 shrink-0 text-haze" />
						{g}
					</li>
				{/each}
			</ul>
		</div>
	</section>

	<!-- cta -->
	<section class="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6">
		<div use:reveal class="glass flex flex-col items-start justify-between gap-6 rounded-[2rem] p-6 shadow-card sm:p-10 md:flex-row md:items-center">
			<div>
				<h2 class="text-2xl font-semibold tracking-tight sm:text-3xl">Open the desk.</h2>
				<p class="mt-2 text-ink-muted">
					Four demo roles: analyst, finance ops, collections and compliance manager. Each sees only what its role allows.
				</p>
			</div>
			<a href="/login" class="group flex shrink-0 items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-medium text-white transition hover:scale-[1.03]">
				Sign in to the demo <ArrowRight size={16} class="transition group-hover:translate-x-0.5" />
			</a>
		</div>
	</section>

	<footer class="border-t border-white/60">
		<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-xs text-ink-muted sm:px-6">
			<span class="flex items-center gap-2"><ShieldCheck size={14} /> Zentry · Vultr Agent Rush 2026</span>
			<span class="flex items-center gap-1.5"><ArrowRightLeft size={13} /> Synthetic data only · no real banks or regulators</span>
		</div>
	</footer>
</div>

<style>
	/* scroll reveal */
	:global(.reveal) {
		opacity: 0;
		transform: translateY(18px);
		transition:
			opacity 0.7s ease var(--d, 0ms),
			transform 0.7s cubic-bezier(0.2, 0.7, 0.2, 1) var(--d, 0ms);
	}
	:global(.reveal.in) {
		opacity: 1;
		transform: none;
	}

	.lift {
		transition:
			transform 0.3s ease,
			box-shadow 0.3s ease;
	}
	.lift:hover {
		transform: translateY(-4px);
		box-shadow: 0 30px 80px rgb(77 80 110 / 0.18);
	}

	/* background */
	.blob {
		position: absolute;
		border-radius: 9999px;
		filter: blur(70px);
		animation: drift 18s ease-in-out infinite alternate;
	}
	.blob-2 {
		animation-duration: 22s;
		animation-delay: -6s;
	}
	.blob-3 {
		animation-duration: 26s;
		animation-delay: -12s;
	}
	@keyframes drift {
		to {
			transform: translate(60px, 40px) scale(1.12);
		}
	}

	/* headline shimmer */
	.shine {
		background: linear-gradient(90deg, #4d506e 0%, #6c72ac 30%, #ec630d 50%, #6c72ac 70%, #4d506e 100%);
		background-size: 250% 100%;
		-webkit-background-clip: text;
		background-clip: text;
		color: transparent;
		animation: shine 7s ease-in-out infinite;
	}
	@keyframes shine {
		0%,
		100% {
			background-position: 100% 0;
		}
		50% {
			background-position: 0 0;
		}
	}

	.live-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 9999px;
		background: #16a34a;
		box-shadow: 0 0 0 0 rgb(22 163 74 / 0.6);
		animation: ping 1.8s ease-out infinite;
	}
	@keyframes ping {
		to {
			box-shadow: 0 0 0 8px rgb(22 163 74 / 0);
		}
	}

	.feed-row {
		animation: slide-in 0.45s cubic-bezier(0.2, 0.7, 0.2, 1);
	}
	@keyframes slide-in {
		from {
			opacity: 0;
			transform: translateY(-12px) scale(0.98);
		}
	}

	.caret {
		animation: blink 1s steps(1) infinite;
		color: #9ca7de;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}

	.float {
		animation: float 5s ease-in-out infinite;
	}
	.float-2 {
		animation-delay: -2.5s;
	}
	@keyframes float {
		50% {
			transform: translateY(-8px);
		}
	}

	.pulse {
		animation: pulse 2s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			box-shadow: 0 0 0 6px rgb(236 99 13 / 0.15);
		}
	}

	/* logo marquee */
	.marquee {
		overflow: hidden;
		padding-block: 6px;
		mask-image: linear-gradient(90deg, transparent, #000 10%, #000 90%, transparent);
	}
	.marquee-track {
		display: flex;
		width: max-content;
		gap: 0.75rem;
		animation: marquee 32s linear infinite;
	}
	.marquee:hover .marquee-track {
		animation-play-state: paused;
	}
	@keyframes marquee {
		to {
			transform: translateX(calc(-50% - 0.375rem));
		}
	}

	.flow {
		animation: march 1.2s linear infinite;
	}
	@keyframes march {
		to {
			stroke-dashoffset: -18;
		}
	}
	.ripple {
		transform-origin: 150px 90px;
		animation: ripple 2.4s ease-out infinite;
	}
	@keyframes ripple {
		from {
			opacity: 0.5;
			transform: scale(1);
		}
		to {
			opacity: 0;
			transform: scale(2.6);
		}
	}

	.bar {
		animation: fill 3.5s ease-in-out infinite;
	}
	@keyframes fill {
		from {
			width: 8%;
		}
		70%,
		to {
			width: 100%;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		* {
			animation: none !important;
			transition: none !important;
		}
		:global(.reveal) {
			opacity: 1;
			transform: none;
		}
	}
</style>
