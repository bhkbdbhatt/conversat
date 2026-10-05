<script lang="ts">
	import { api } from '$lib/api';
	import { dateTime, duration, percent, relativeTime } from '$lib/format';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import type { RunSummary } from '$lib/types';

	let runs = $state<RunSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let filter = $state('');
	let status = $state<'all' | 'passed' | 'failed'>('all');

	async function load() {
		loading = true;
		try {
			runs = await api.runs();
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void load();
	});

	const filtered = $derived(
		runs.filter((run) => {
			if (status !== 'all' && run.status !== status) return false;
			if (!filter.trim()) return true;
			const needle = filter.toLowerCase();
			return (
				run.suite.toLowerCase().includes(needle) ||
				run.run_id.toLowerCase().includes(needle) ||
				run.labels.some((label) => label.toLowerCase().includes(needle))
			);
		})
	);
</script>

<svelte:head><title>conversat — runs</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Runs</h1>
		<p>Every run report found in the reports directory, newest first.</p>
	</div>
	<div class="row">
		<select bind:value={status} style="width: auto" aria-label="Filter by status">
			<option value="all">all statuses</option>
			<option value="passed">passed</option>
			<option value="failed">failed</option>
		</select>
		<input placeholder="filter by suite, id or label" bind:value={filter} style="width: 220px" />
		<button class="ghost" onclick={load} disabled={loading}>refresh</button>
	</div>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{/if}

<div class="panel">
	<div class="panel-body flush">
		{#if loading && !runs.length}
			<div class="loading"><span class="spinner"></span>loading…</div>
		{:else if !runs.length}
			<EmptyState
				title="No runs recorded"
				body="Nothing in the reports directory yet. Run `conversat run <suite>` or start one from the overview."
				href="/"
				linkText="Go to overview"
			/>
		{:else if !filtered.length}
			<EmptyState title="No matches" body="Nothing matches that filter." action={load} actionText="Clear filter" />
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Suite</th>
							<th>Status</th>
							<th class="num">Cases</th>
							<th class="num">Turns</th>
							<th class="num">Assertions</th>
							<th class="num">Pass rate</th>
							<th class="num">p95</th>
							<th class="num">Duration</th>
							<th>Started</th>
							<th>Labels</th>
						</tr>
					</thead>
					<tbody>
						{#each filtered as run (run.run_id)}
							<tr>
								<td>
									<a href="/runs/{run.run_id}">{run.suite}</a>
									<div class="faint small mono">{run.connector}</div>
								</td>
								<td><StatusBadge status={run.status} /></td>
								<td class="num">{run.totals.cases_passed}/{run.totals.cases}</td>
								<td class="num">{run.totals.turns_passed}/{run.totals.turns}</td>
								<td class="num">{run.totals.assertions_passed}/{run.totals.assertions}</td>
								<td class="num">{percent(run.totals.cases ? (run.totals.cases_passed / run.totals.cases) * 100 : 0, 0)}</td>
								<td class="num">{duration(run.totals.response_p95_ms)}</td>
								<td class="num">{duration(run.duration_ms)}</td>
								<td class="nowrap" title={dateTime(run.started_at)}>{relativeTime(run.started_at)}</td>
								<td>
									{#each run.labels as label (label)}
										<span class="tag">{label}</span>
									{/each}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>