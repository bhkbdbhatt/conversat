<script lang="ts">
	import { api } from '$lib/api';
	import { count, dateTime, duration, percent, relativeTime } from '$lib/format';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PassRateChart from '$lib/components/PassRateChart.svelte';
	import RunLauncher from '$lib/components/RunLauncher.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { goto } from '$app/navigation';
	import type { LiveSnapshot, RunSummary, Stats, SuiteSummary, TrendPoint } from '$lib/types';

	let stats = $state<Stats | null>(null);
	let runs = $state<RunSummary[]>([]);
	let trends = $state<TrendPoint[]>([]);
	let suites = $state<SuiteSummary[]>([]);
	let active = $state<LiveSnapshot[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		try {
			const [nextStats, nextRuns, nextTrends, nextSuites, nextActive] = await Promise.all([
				api.stats(),
				api.runs(),
				api.trends(30),
				api.suites(),
				api.activeRuns()
			]);
			stats = nextStats;
			runs = nextRuns;
			trends = nextTrends;
			suites = nextSuites.suites;
			active = nextActive;
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void load();
		const timer = setInterval(() => void load(), 10_000);
		return () => clearInterval(timer);
	});

	const passRate = $derived(
		stats && stats.cases ? ((stats.cases - stats.failed_cases) / stats.cases) * 100 : null
	);
	const recent = $derived(runs.slice(0, 8));

	function follow(runIds: string[]) {
		if (runIds.length === 1) goto(`/live/${runIds[0]}`);
		else goto('/live');
	}
</script>

<svelte:head><title>conversat — overview</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Overview</h1>
		<p>Conversational test runs recorded on this machine.</p>
	</div>
	<button class="ghost" onclick={load} disabled={loading}>refresh</button>
</div>

<div class="stack">
	{#if error}
		<div class="notice bad">{error}</div>
	{/if}

	{#if loading && !stats}
		<div class="loading"><span class="spinner"></span>loading…</div>
	{:else}
		<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(160px, 1fr))">
			<StatCard label="Runs" value={count(stats?.runs)} hint="{count(runs.length)} in memory" />
			<StatCard label="Cases" value={count(stats?.cases)} hint="{count(stats?.failed_cases)} failing" tone={stats?.failed_cases ? 'bad' : undefined} />
			<StatCard label="Pass rate" value={percent(passRate)} tone={passRate === 100 ? 'ok' : passRate === null ? undefined : 'warn'} />
			<StatCard label="Assertions" value={count(stats?.assertions)} />
			<StatCard label="Avg duration" value={duration(stats?.avg_duration_ms)} />
		</div>

		{#if active.length}
			<div class="notice warn">
				{active.length} run{active.length === 1 ? '' : 's'} in progress —
				<a href="/live">watch live</a>
			</div>
		{/if}

		<div class="grid" style="grid-template-columns: minmax(280px, 1fr) minmax(320px, 2fr); align-items: start">
			<RunLauncher {suites} onstarted={follow} />

			<div class="panel">
				<div class="panel-head">
					<h2>Pass-rate trend</h2>
					<a class="button" href="/runs">all runs</a>
				</div>
				<div class="panel-body">
					<PassRateChart points={trends} />
				</div>
			</div>
		</div>

		<div class="panel">
			<div class="panel-head">
				<h2>Recent runs</h2>
				<span class="faint small">newest first</span>
			</div>
			<div class="panel-body flush">
				{#if !recent.length}
					<EmptyState
						title="No runs yet"
						body="Trigger one above, or run `conversat run examples/suites/echo.yaml` in a terminal — reports on disk show up here automatically."
					/>
				{:else}
					<div class="table-wrap">
						<table>
							<thead>
								<tr>
									<th>Suite</th>
									<th>Status</th>
									<th class="num">Cases</th>
									<th class="num">Assertions</th>
									<th class="num">p95</th>
									<th class="num">Duration</th>
									<th>Started</th>
								</tr>
							</thead>
							<tbody>
								{#each recent as run (run.run_id)}
									<tr>
										<td>
											<a href="/runs/{run.run_id}">{run.suite}</a>
											<div class="faint small mono">{run.run_id}</div>
										</td>
										<td><StatusBadge status={run.status} /></td>
										<td class="num">{run.totals.cases_passed}/{run.totals.cases}</td>
										<td class="num">{run.totals.assertions_passed}/{run.totals.assertions}</td>
										<td class="num">{duration(run.totals.response_p95_ms)}</td>
										<td class="num">{duration(run.duration_ms)}</td>
										<td class="nowrap" title={dateTime(run.started_at)}>{relativeTime(run.started_at)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>