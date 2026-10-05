<script lang="ts">
	import EmptyState from './EmptyState.svelte';
	import StatusBadge from './StatusBadge.svelte';
	import Transcript from './Transcript.svelte';
	import type { LiveRunView } from '$lib/live-state.svelte';
	import { duration, percent } from '$lib/format';

	let { view }: { view: LiveRunView } = $props();

	const totals = $derived(view.totals);
</script>

<div class="stack">
	<div class="row">
		<strong>{view.suite || 'Waiting for the suite name…'}</strong>
		<StatusBadge status={view.status} />
		<span
			class="badge {view.connection === 'open'
				? 'ok'
				: view.connection === 'connecting'
					? 'busy'
					: 'muted'} dot"
		>
			{view.connection === 'open' ? 'streaming' : view.connection}
		</span>
		<span class="grow" style="flex: 1"></span>
		<span class="faint small">
			{view.cases.length} case(s) · {view.completedCases} finished · {view.failedTurns} failing turn(s)
			· {view.events} event(s)
		</span>
	</div>

	{#if view.error}
		<div class="notice bad">{view.error}</div>
	{/if}

	{#if totals}
		<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))">
			<div class="stat">
				<span class="label">Cases passed</span>
				<span class="value">{totals.cases_passed ?? 0}/{totals.cases ?? 0}</span>
			</div>
			<div class="stat">
				<span class="label">Assertions</span>
				<span class="value">{totals.assertions_passed ?? 0}/{totals.assertions ?? 0}</span>
			</div>
			<div class="stat">
				<span class="label">Turns</span>
				<span class="value">{totals.turns ?? 0}</span>
			</div>
			<div class="stat">
				<span class="label">p95</span>
				<span class="value">{duration(Number(totals.response_p95_ms ?? 0))}</span>
			</div>
			<div class="stat">
				<span class="label">Pass rate</span>
				<span class="value">
					{percent(totals.cases ? (totals.cases_passed / totals.cases) * 100 : 0)}
				</span>
			</div>
		</div>
	{/if}

	{#if !view.active && !view.cases.length}
		<EmptyState
			title="Nothing streamed"
			body="This run started before the server came up, or its events have rolled off. The full report is still available."
			href={view.runId ? `/runs/${view.runId}` : '/runs'}
			linkText={view.runId ? 'Open the report' : 'See all runs'}
		/>
	{/if}

	{#each view.cases as item (item.name)}
		<details class="disclosure" open={item.status !== 'passed' || view.active}>
			<summary>
				<StatusBadge status={item.status} />
				<strong>{item.name}</strong>
				<span class="faint small">
					{item.turns.length} turn{item.turns.length === 1 ? '' : 's'}
					{#if item.error}· <span style="color: var(--bad)">{item.error}</span>{/if}
				</span>
			</summary>
			<div class="disclosure-body">
				<div class="transcript">
					{#each item.turns as turn (turn.index)}
						<Transcript {turn} pending={!turn.reply && item.status === 'running'} />
					{/each}
					{#if !item.turns.length}
						<div class="bubble-row">
							<div class="bubble bot empty-reply"><span class="spinner"></span>running…</div>
						</div>
					{/if}
				</div>
			</div>
		</details>
	{/each}
</div>