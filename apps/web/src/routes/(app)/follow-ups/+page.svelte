<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onMount } from 'svelte';
	import { browserSupabase } from '#lib/supabase.ts';
	import { thb } from '#lib/money.ts';
	import { KIND_LABEL, STAGES, type FollowUp } from '#lib/recon.ts';
	import { Bot, CalendarClock, Check, Inbox, MessageSquareReply, Play, Send, X } from '@lucide/svelte';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();

	const canAct = $derived(['collections', 'finance_ops', 'compliance_manager', 'admin'].includes(data.role ?? ''));
	let picked = $state<string | null>(null);
	const sel = $derived(data.items.find((f) => f.id === picked) ?? data.items.find((f) => f.stage !== 'closed'));
	const thread = $derived(data.messages.filter((m) => m.follow_up_id === sel?.id));
	const draft = $derived(thread.find((m) => m.status === 'draft'));
	const pending = $derived(new Set(data.messages.filter((m) => m.status === 'draft').map((m) => m.follow_up_id)));
	const due = $derived(data.items.filter((f) => f.stage !== 'closed').reduce((s, f) => s + f.amount_due_satang, 0));

	onMount(() => {
		const supabase = browserSupabase();
		let channel: ReturnType<typeof supabase.channel> | undefined;
		supabase.auth.getSession().then(({ data: { session } }) => {
			if (session) supabase.realtime.setAuth(session.access_token);
			channel = supabase
				.channel('follow-ups')
				.on('postgres_changes', { event: '*', schema: 'public', table: 'follow_ups' }, () => invalidate('app:follow-ups'))
				.on('postgres_changes', { event: '*', schema: 'public', table: 'messages' }, () => invalidate('app:follow-ups'))
				.subscribe();
		});
		return () => channel && supabase.removeChannel(channel);
	});

	const day = (d: string | null) =>
		d ? new Date(d.length === 10 ? `${d}T00:00:00+07:00` : d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'Asia/Bangkok' }) : '—';
	const when = (d: string | null) =>
		d ? new Date(d).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Bangkok' }) : '';
	const kindTone = (f: FollowUp) => (f.kind === 'victim_refund' ? 'bg-alert/10 text-alert' : 'bg-accent/15 text-accent');
	const LEVEL = ['', 'Friendly reminder', 'Firm reminder', 'Escalation notice'];
</script>

<section class="mx-auto flex max-w-7xl flex-col pt-4 xl:h-full">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">Payment Follow-ups</h1>
			<p class="mt-1 text-sm text-ink-muted">
				{data.items.filter((f) => f.stage !== 'closed').length} open · {thb(due)} outstanding · {pending.size} drafts waiting for approval
			</p>
		</div>
		<span class="flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium shadow-card">
			<Inbox size={14} class="text-accent" /> Approved messages go to a simulated inbox
		</span>
	</div>

	{#if form?.message}
		<p class="mt-4 rounded-2xl bg-ink px-4 py-2.5 text-sm text-white">{form.message}</p>
	{/if}

	{#if !data.items.length}
		<div class="mt-8 rounded-3xl bg-white p-10 text-center shadow-card">
			<Inbox class="mx-auto text-accent" />
			<p class="mt-3 font-medium">Nothing to follow up yet</p>
			<p class="mt-1 text-sm text-ink-muted">Follow-ups open when Finance Ops confirms a recon break we are owed, or an analyst closes a mule case as fraud with victim money still held.</p>
		</div>
	{:else}
		<div class="mt-5 grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
			<!-- kanban -->
			<div class="grid min-h-0 grid-cols-2 gap-3 md:grid-cols-5">
				{#each STAGES as col (col.stage)}
					{@const cards = data.items.filter((f) => f.stage === col.stage)}
					<div class="flex min-h-0 min-w-0 flex-col rounded-3xl bg-white/50 p-2">
						<p class="flex items-center justify-between px-2 py-1 text-xs font-medium text-ink-muted">{col.label}<span>{cards.length}</span></p>
						<div class="mt-1 max-h-[620px] min-h-0 flex-1 space-y-2 overflow-auto xl:max-h-none">
							{#each cards as f (f.id)}
								<button onclick={() => (picked = f.id)}
									class="w-full rounded-2xl bg-white p-3 text-left shadow-card transition {sel?.id === f.id ? 'ring-2 ring-ink' : 'hover:ring-1 hover:ring-haze'}">
									<span class="rounded-full px-2 py-0.5 text-[10px] whitespace-nowrap {kindTone(f)}">{KIND_LABEL[f.kind]}</span>
									<p class="mt-1.5 line-clamp-2 text-xs font-medium">{f.counterparty}</p>
									<p class="mt-0.5 text-sm font-semibold tabular-nums">{thb(f.amount_due_satang)}</p>
									<p class="mt-1 flex items-center gap-1 text-[10px] text-ink-muted">
										{#if pending.has(f.id)}<Bot size={11} class="text-alert" /> draft waiting
										{:else if f.promise_date && f.stage === 'promised'}<CalendarClock size={11} /> promised {day(f.promise_date)}
										{:else if f.closed_reason}{f.closed_reason}
										{:else}due {day(f.due_date)}{/if}
									</p>
								</button>
							{/each}
						</div>
					</div>
				{/each}
			</div>

			<!-- detail -->
			{#if sel}
				<div class="min-h-0 space-y-4 overflow-y-auto rounded-3xl bg-white p-5 shadow-card">
					<div>
						<span class="rounded-full px-2 py-0.5 text-[11px] {kindTone(sel)}">{KIND_LABEL[sel.kind]}</span>
						<h2 class="mt-2 font-semibold">{sel.title}</h2>
						<p class="text-xs text-ink-muted">{sel.counterparty} · {sel.contact}</p>
						<div class="mt-3 grid grid-cols-3 gap-2 text-xs">
							<div class="rounded-2xl bg-mist p-2.5"><p class="text-ink-muted">Amount</p><p class="font-semibold tabular-nums">{thb(sel.amount_due_satang)}</p></div>
							<div class="rounded-2xl bg-mist p-2.5"><p class="text-ink-muted">Stage</p><p class="font-semibold capitalize">{sel.stage}{sel.level ? ` · L${sel.level}` : ''}</p></div>
							<div class="rounded-2xl bg-mist p-2.5"><p class="text-ink-muted">{sel.promise_date ? 'Promised' : 'Due'}</p><p class="font-semibold">{day(sel.promise_date ?? sel.due_date)}</p></div>
						</div>
						{#if sel.case_id}<a href="/cases/{sel.case_id}" class="mt-2 inline-block text-xs text-accent underline">Open mule case</a>{/if}
						{#if sel.next_action_at && sel.stage !== 'closed'}<p class="mt-1 text-[11px] text-ink-muted">Next agent check {when(sel.next_action_at)}</p>{/if}
					</div>

					{#if draft && canAct}
						<form method="POST" action="?/approve" use:enhance class="space-y-2 rounded-2xl border border-alert/30 p-3">
							<p class="flex items-center gap-1.5 text-xs font-medium"><Bot size={13} class="text-accent" /> Agent draft · {sel.kind === 'victim_refund' ? `Progress update ${draft.level}` : LEVEL[draft.level ?? 0]}
								<span class="ml-auto text-[10px] font-normal text-ink-muted">{draft.author}</span></p>
							<input type="hidden" name="id" value={draft.id} />
							<input name="subject" value={draft.subject} class="w-full rounded-xl bg-mist px-3 py-2 text-xs font-medium" />
							<textarea name="body" rows="9" class="w-full rounded-xl bg-mist px-3 py-2 text-xs leading-relaxed">{draft.draft}</textarea>
							<div class="flex gap-2">
								<button class="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-ink py-2 text-xs font-medium text-white"><Send size={13} /> Approve & send</button>
								<button formaction="?/reject" class="flex items-center gap-1.5 rounded-full bg-mist px-4 py-2 text-xs font-medium"><X size={13} /> Reject</button>
							</div>
						</form>
					{/if}

					<div class="max-h-64 space-y-2 overflow-auto">
						{#each thread.filter((m) => m.status !== 'draft') as m (m.id)}
							<div class="rounded-2xl p-3 text-xs {m.direction === 'in' ? 'ml-6 bg-mist' : 'mr-6 border border-mist'} {m.status === 'rejected' ? 'opacity-50' : ''}">
								<p class="flex justify-between gap-2 text-[10px] text-ink-muted">
									<span>{m.direction === 'in' ? 'Reply' : m.status === 'rejected' ? 'Rejected draft' : 'Sent'} · {when(m.sent_at ?? m.created_at)}</span>
									{#if m.level}<span>L{m.level}</span>{/if}
								</p>
								{#if m.subject}<p class="mt-1 font-medium">{m.direction === 'in' ? `Agent: ${m.subject}` : m.subject}</p>{/if}
								<p class="mt-1 line-clamp-4 whitespace-pre-line">{m.draft}</p>
							</div>
						{/each}
					</div>

					{#if canAct && sel.stage !== 'closed'}
						<form method="POST" action="?/reply" use:enhance class="flex gap-2">
							<input type="hidden" name="id" value={sel.id} />
							<input name="text" required placeholder="Paste their reply, e.g. “จะโอนให้วันศุกร์นี้ครับ”" class="min-w-0 flex-1 rounded-full bg-mist px-3 py-2 text-xs" />
							<button class="flex items-center gap-1 rounded-full bg-mist px-3 text-xs font-medium"><MessageSquareReply size={13} /> Log reply</button>
						</form>
						<div class="flex flex-wrap gap-2">
							{#if !draft}
								<form method="POST" action="?/run" use:enhance>
									<input type="hidden" name="id" value={sel.id} />
									<button class="flex items-center gap-1.5 rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white"><Play size={12} /> Run agent now</button>
								</form>
							{/if}
							<form method="POST" action="?/close" use:enhance class="flex gap-1.5">
								<input type="hidden" name="id" value={sel.id} />
								<select name="reason" class="rounded-full bg-mist px-2 text-xs" aria-label="Close reason">
									<option value={sel.kind === 'victim_refund' ? 'refunded' : 'paid'}>{sel.kind === 'victim_refund' ? 'Refunded' : 'Paid'}</option>
									<option value="written_off">Written off</option>
									<option value="not_needed">Not needed</option>
								</select>
								<button class="flex items-center gap-1 rounded-full bg-mist px-3 py-1.5 text-xs font-medium"><Check size={12} /> Close</button>
							</form>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</section>
