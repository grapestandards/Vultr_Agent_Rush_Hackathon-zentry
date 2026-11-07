<script lang="ts">
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
		Network,
		Play,
		Radio,
		ShieldCheck,
		Sparkles,
		UserCheck
	} from '@lucide/svelte';

	const stack = ['Vultr Cloud Compute', 'Vultr Serverless Inference', 'NATS JetStream', 'Supabase · Postgres', 'LightGBM + SHAP', 'SvelteKit'];

	const stats = [
		{ value: '199,736', label: 'transfers scored in one replay' },
		{ value: '5 / 5', label: 'mule rings grouped into cases' },
		{ value: '60 / 60', label: 'reconciliation breaks found, 0 false' },
		{ value: '100%', label: 'agent claims backed by real txn ids' }
	];

	const steps = [
		{ n: '01', title: 'Stream', icon: Radio, body: 'Every e-wallet transfer lands in an outbox and streams through NATS JetStream, exactly once.' },
		{ n: '02', title: 'Score', icon: BellRing, body: 'LightGBM plus five explainable rules score each transfer in milliseconds; graph analysis groups alerts into cases.' },
		{ n: '03', title: 'Investigate', icon: BrainCircuit, body: 'An agent on Vultr Serverless Inference walks the money with read-only tools and writes a cited report.' },
		{ n: '04', title: 'Decide', icon: UserCheck, body: 'Analysts freeze, file STRs, confirm journal entries and approve messages. Every decision is audited.' }
	];

	const rules = [
		{ name: 'pass_through', hit: true },
		{ name: 'fan_in_out', hit: true },
		{ name: 'new_account_strangers', hit: true },
		{ name: 'structuring', hit: false },
		{ name: 'dormant_reactivation', hit: false }
	];

	const breaks = [
		{ label: 'Fee', n: 10 },
		{ label: 'Timing', n: 10 },
		{ label: 'Duplicate', n: 10 },
		{ label: 'Amount mismatch', n: 10 },
		{ label: 'Missing in bank', n: 10 },
		{ label: 'Missing in ledger', n: 10 }
	];

	const guardrails = [
		'Read tools run in READ ONLY transactions; propose_action is the only writer',
		'A validator rejects reports citing ids that do not exist or were not returned by a tool',
		'Freezes, STRs, outbound messages and model promotion wait for a human',
		'Every prompt, output and decision is written to the audit log',
		'Full names only via an audited reveal with a stated reason',
		'Money is integer satang end to end. No floats, ever'
	];

	// tiny static graph for the capability card
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
		content="Zentry is an agentic financial-crime and payment-ops desk for Thai e-wallets: real-time mule detection, cited AI investigations, reconciliation and payment follow-ups on Vultr."
	/>
</svelte:head>

<div class="min-h-dvh overflow-x-clip">
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
			<a href="/login" class="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-sm font-medium text-white">
				Open the desk <ArrowRight size={14} />
			</a>
		</nav>
	</header>

	<!-- hero -->
	<section class="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-14 pb-10 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
		<div>
			<p class="text-xs font-semibold tracking-[0.18em] text-accent">FINANCIAL CRIME · PAYMENT OPS</p>
			<h1 class="mt-4 text-4xl leading-[1.05] font-semibold tracking-tight sm:text-6xl">
				Follow the money.<br /><span class="text-ink-muted">Close the books.</span>
			</h1>
			<p class="mt-5 max-w-xl text-lg text-ink-muted">
				One desk for Thai e-wallets: catch money-mule rings in real time, let an agent investigate with cited evidence,
				reconcile bank and gateway files, and chase payments. Humans approve every action.
			</p>
			<div class="mt-7 flex flex-wrap items-center gap-3">
				<a href="/login" class="flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-medium text-white shadow-panel">
					Try the live demo <ArrowRight size={16} />
				</a>
				<a href="#demo" class="flex items-center gap-2 rounded-full bg-white px-5 py-3 text-sm font-medium shadow-card">
					<Play size={15} class="text-accent" /> Watch the tour (1:09)
				</a>
			</div>
			<p class="mt-5 text-xs text-ink-muted">Synthetic data only. Not connected to any real bank or regulator.</p>
		</div>

		<!-- hero card: a case, didit-style subject card -->
		<div class="relative">
			<div class="absolute -inset-6 -z-10 rounded-[2.5rem] bg-haze/40 blur-2xl"></div>
			<div class="glass rounded-3xl p-5 shadow-panel">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-3">
						<span class="grid size-10 place-items-center rounded-full bg-alert text-white"><Network size={18} /></span>
						<div>
							<p class="text-xs text-ink-muted">CASE · mule ring</p>
							<p class="font-semibold">Layered network around A0004094</p>
						</div>
					</div>
					<span class="shrink-0 rounded-full bg-alert/10 px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-alert">risk 97</span>
				</div>
				<div class="mt-4 grid grid-cols-3 gap-2">
					{#each [{ k: 'Accounts', v: '18' }, { k: 'Transfers', v: '85' }, { k: 'Held', v: '฿578,975' }] as s (s.k)}
						<div class="rounded-2xl bg-white p-3 shadow-card">
							<p class="text-[11px] text-ink-muted">{s.k}</p>
							<p class="text-lg font-semibold">{s.v}</p>
						</div>
					{/each}
				</div>
				<div class="mt-3 rounded-2xl bg-white p-4 shadow-card">
					<p class="flex items-center gap-1.5 text-xs font-medium text-accent"><Sparkles size={13} /> Agent report · verified</p>
					<p class="mt-2 text-sm leading-relaxed">
						A0004094 sent ฿28,774.05 to A0006872
						<code class="rounded bg-mist px-1 text-[11px]">TX00120342</code> and ฿297,836.88 to A0011519
						<code class="rounded bg-mist px-1 text-[11px]">TX00120956</code> from the same device, then balances were pushed
						to QR merchants for cash-out…
					</p>
					<div class="mt-3 flex flex-wrap gap-1.5">
						{#each ['pass_through', 'fan_in_out', 'shared device'] as t (t)}
							<span class="rounded-full bg-ink px-2.5 py-1 text-[11px] text-white">{t}</span>
						{/each}
					</div>
				</div>
				<div class="mt-3 flex items-center justify-between rounded-2xl bg-ink px-4 py-3 text-white">
					<span class="text-sm">Proposed: freeze 6 accounts + STR</span>
					<span class="flex items-center gap-1 text-xs text-white/70"><Lock size={12} /> awaits analyst</span>
				</div>
			</div>
		</div>
	</section>

	<!-- built on -->
	<section class="mx-auto max-w-6xl px-4 pb-6 sm:px-6">
		<p class="text-center text-xs font-semibold tracking-[0.18em] text-ink-muted">BUILT ON</p>
		<div class="mt-4 flex flex-wrap justify-center gap-2">
			{#each stack as s (s)}
				<span class="rounded-full bg-white/80 px-4 py-2 text-sm font-medium shadow-card">{s}</span>
			{/each}
		</div>
	</section>

	<!-- stats -->
	<section class="mx-auto max-w-6xl px-4 py-10 sm:px-6">
		<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
			{#each stats as s (s.label)}
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<p class="text-3xl font-semibold tracking-tight">{s.value}</p>
					<p class="mt-1 text-sm text-ink-muted">{s.label}</p>
				</div>
			{/each}
		</div>
	</section>

	<!-- how it works -->
	<section id="how" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<p class="text-xs font-semibold tracking-[0.18em] text-accent">HOW IT WORKS</p>
		<h2 class="mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">From transfer to decision in four steps.</h2>
		<div class="mt-8 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
			{#each steps as s (s.n)}
				<div class="glass rounded-3xl p-5 shadow-card">
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
		<p class="text-xs font-semibold tracking-[0.18em] text-accent">DETECT · INVESTIGATE · RECONCILE · FOLLOW UP</p>
		<h2 class="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Six capabilities. One desk. Agents that show their work.</h2>

		<div class="mt-10 space-y-6">
			<!-- 01 detection -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">01 · REAL-TIME DETECTION</p>
					<h3 class="mt-2 text-2xl font-semibold">A model and five rules you can explain.</h3>
					<p class="mt-3 text-ink-muted">
						LightGBM scores every transfer on velocity, counterparty, device and graph features, computed by the same
						FeatureEngine in training and live. Five rules with thresholds you can tune name the pattern, and SHAP shows why.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between">
						<p class="text-sm font-medium">TX00120956 · ฿297,836.88</p>
						<span class="rounded-full bg-alert px-2.5 py-1 text-xs font-semibold text-white">score 97</span>
					</div>
					<div class="mt-4 space-y-2">
						{#each rules as r (r.name)}
							<div class="flex items-center justify-between rounded-xl bg-mist/70 px-3 py-2 text-sm">
								<code class="text-[13px]">{r.name}</code>
								{#if r.hit}
									<span class="text-xs font-semibold text-alert">HIT</span>
								{:else}
									<span class="text-xs text-ink-muted">clear</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			</article>

			<!-- 02 agent -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">02 · CITED AI INVESTIGATIONS</p>
					<h3 class="mt-2 text-2xl font-semibold">No transaction id, no claim.</h3>
					<p class="mt-3 text-ink-muted">
						The investigator runs on Vultr Serverless Inference with read-only tools for history, money tracing and name
						screening. A validator checks every id it cites against the database and the tool outputs before an analyst
						sees the report.
					</p>
				</div>
				<div class="rounded-3xl bg-ink p-5 font-mono text-[12.5px] leading-relaxed text-white/90 shadow-panel lg:order-1">
					<p class="text-white/50">// tool calls (read only)</p>
					<p>get_account_history("A0006872") <span class="text-emerald-300">→ 39 rows</span></p>
					<p>trace_money("A0004094", hops=3) <span class="text-emerald-300">→ 18 accounts</span></p>
					<p>screen_name("A0011519") <span class="text-emerald-300">→ Anucha Ka****</span></p>
					<p class="mt-3 text-white/50">// validator</p>
					<p>cited ids <span class="text-white">142</span> · in DB <span class="text-emerald-300">142</span> · from tools <span class="text-emerald-300">142</span></p>
					<p class="mt-3 inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-3 py-1 text-emerald-300">
						<BadgeCheck size={14} /> report valid · shown to analyst
					</p>
				</div>
			</article>

			<!-- 03 graph -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">03 · GRAPH EXPLORER</p>
					<h3 class="mt-2 text-2xl font-semibold">See the ring, not just the row.</h3>
					<p class="mt-3 text-ink-muted">
						Flows in green and out in red, a time slider, network detection, and "trace from victim" to work out how much
						can still be recovered. Click any node to open its entity page.
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
						{#each ring as n, i (i)}
							<circle cx={n.x} cy={n.y} r={n.r} fill={n.c} stroke="white" stroke-width="2" />
						{/each}
						<text x="315" y="120" text-anchor="middle" font-size="10" fill="#4D506E">Gold Shop</text>
						<text x="150" y="122" text-anchor="middle" font-size="10" fill="#4D506E">collector</text>
					</svg>
				</div>
			</article>

			<!-- 04 recon -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">04 · RECONCILIATION</p>
					<h3 class="mt-2 text-2xl font-semibold">Three passes. Balanced entries.</h3>
					<p class="mt-3 text-ink-muted">
						Exact reference, fuzzy amount, time and name, then many-to-one gateway batches with fee checks. Each break is
						typed, explained and paired with a balanced journal entry for finance to confirm or dismiss.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card lg:order-1">
					<div class="flex items-end justify-between">
						<div>
							<p class="text-xs text-ink-muted">Auto-match rate</p>
							<p class="text-3xl font-semibold">99.93%</p>
						</div>
						<p class="text-sm text-ink-muted">87,882 matched</p>
					</div>
					<div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
						{#each breaks as b (b.label)}
							<div class="rounded-xl bg-mist/70 px-3 py-2">
								<p class="text-[11px] text-ink-muted">{b.label}</p>
								<p class="font-semibold text-alert">{b.n}</p>
							</div>
						{/each}
					</div>
					<div class="mt-3 rounded-xl border border-mist px-3 py-2 text-xs">
						<div class="flex justify-between"><span>Dr 1120 Settlement clearing</span><span>฿473.93</span></div>
						<div class="flex justify-between text-ink-muted"><span>Cr 2190 Suspense</span><span>฿473.93</span></div>
					</div>
				</div>
			</article>

			<!-- 05 follow-ups -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div>
					<p class="text-sm font-semibold text-accent">05 · PAYMENT FOLLOW-UPS</p>
					<h3 class="mt-2 text-2xl font-semibold">Polite first. Firm when needed.</h3>
					<p class="mt-3 text-ink-muted">
						The agent drafts Thai and English reminders on a three-step ladder, reads replies for promised pay dates, and
						opens victim-refund updates when a case is confirmed as fraud. Nothing leaves without approval.
					</p>
				</div>
				<div class="rounded-3xl bg-white p-5 shadow-card">
					<div class="flex items-center justify-between text-xs text-ink-muted">
						<span class="flex items-center gap-1.5"><Mail size={13} /> Draft · L1 friendly</span>
						<span>due 21 Nov</span>
					</div>
					<p class="mt-3 font-[IBM_Plex_Sans_Thai] text-sm">เรียน ร้านทองเยาวราช กรุณาตรวจสอบค่าธรรมเนียม ฿1,250.00 ที่ยังค้างชำระ…</p>
					<p class="mt-2 text-sm text-ink-muted">Dear Yaowarat Gold Shop, a fee of ฿1,250.00 is still outstanding…</p>
					<div class="mt-4 flex gap-2">
						<span class="flex items-center gap-1 rounded-full bg-ink px-3 py-1.5 text-xs text-white"><Check size={12} /> Approve & send</span>
						<span class="rounded-full bg-mist px-3 py-1.5 text-xs">Reject</span>
					</div>
				</div>
			</article>

			<!-- 06 privacy -->
			<article class="grid items-center gap-6 rounded-[2rem] bg-white/60 p-5 shadow-card sm:p-8 lg:grid-cols-2">
				<div class="lg:order-2">
					<p class="text-sm font-semibold text-accent">06 · PRIVACY & TUNING</p>
					<h3 class="mt-2 text-2xl font-semibold">Masked by default. Better every week.</h3>
					<p class="mt-3 text-ink-muted">
						Browsers can only read masked names. Seeing a full name takes a role, a reason and an audit entry. Analyst
						decisions become labels: train a challenger, compare it with the champion, and promote it only with approval.
					</p>
				</div>
				<div class="space-y-3 lg:order-1">
					<div class="flex items-center justify-between rounded-3xl bg-white p-4 shadow-card">
						<div class="flex items-center gap-3">
							<span class="grid size-10 place-items-center rounded-full bg-alert text-white"><EyeOff size={16} /></span>
							<div>
								<p class="font-semibold">Somying Sd****</p>
								<p class="text-xs text-ink-muted">A0006872 · PII masked</p>
							</div>
						</div>
						<span class="rounded-full bg-mist px-3 py-1.5 text-xs">Reveal · reason required</span>
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div class="rounded-3xl bg-white p-4 shadow-card">
							<p class="text-xs text-ink-muted">Champion PR-AUC</p>
							<p class="text-2xl font-semibold">0.9844</p>
						</div>
						<div class="rounded-3xl bg-white p-4 shadow-card">
							<p class="text-xs text-ink-muted">Mule accounts caught</p>
							<p class="text-2xl font-semibold">100%</p>
						</div>
					</div>
				</div>
			</article>
		</div>
	</section>

	<!-- demo video -->
	<section id="demo" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div class="text-center">
			<p class="text-xs font-semibold tracking-[0.18em] text-accent">PRODUCT TOUR</p>
			<h2 class="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">See a mule ring go from alert to decision.</h2>
		</div>
		<div class="relative mt-8">
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
					class="aspect-[16/10] w-full rounded-2xl bg-ink object-cover"
					src="/demo/zentry-demo.mp4"
					poster="/demo/poster.jpg"
					controls
					playsinline
					preload="metadata"
				></video>
			</div>
		</div>
	</section>

	<!-- guardrails -->
	<section id="guardrails" class="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
		<div class="grid gap-8 rounded-[2rem] bg-ink p-6 text-white shadow-panel sm:p-10 lg:grid-cols-[1fr_1.3fr]">
			<div>
				<p class="text-xs font-semibold tracking-[0.18em] text-haze">GUARDRAILS</p>
				<h2 class="mt-3 text-3xl font-semibold tracking-tight">Agents propose. People decide.</h2>
				<p class="mt-3 text-white/70">
					Built for regulated work. Each agent has a narrow toolset, a validator and an audit trail, so a reviewer can
					trace every sentence back to data.
				</p>
			</div>
			<ul class="grid gap-3 sm:grid-cols-2">
				{#each guardrails as g (g)}
					<li class="flex gap-3 rounded-2xl bg-white/5 p-4 text-sm text-white/85">
						<FileCheck2 size={18} class="mt-0.5 shrink-0 text-haze" />
						{g}
					</li>
				{/each}
			</ul>
		</div>
	</section>

	<!-- cta -->
	<section class="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6">
		<div class="glass flex flex-col items-start justify-between gap-6 rounded-[2rem] p-6 shadow-card sm:p-10 md:flex-row md:items-center">
			<div>
				<h2 class="text-2xl font-semibold tracking-tight sm:text-3xl">Open the desk.</h2>
				<p class="mt-2 text-ink-muted">
					Four demo roles: analyst, finance ops, collections and compliance manager. Each sees only what its role allows.
				</p>
			</div>
			<a href="/login" class="flex shrink-0 items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-medium text-white">
				Sign in to the demo <ArrowRight size={16} />
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
	.flow {
		animation: march 1.2s linear infinite;
	}
	@keyframes march {
		to {
			stroke-dashoffset: -18;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flow {
			animation: none;
		}
	}
</style>
