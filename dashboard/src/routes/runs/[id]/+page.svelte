<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { count, dateTime, duration, percent } from '$lib/format';
	import CaseTranscript from '$lib/components/CaseTranscript.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Transcript from '$lib/components/Transcript.svelte';
	import type { CaseResult, RunReport, TurnRecord } from '$lib/types';

	let report = $state<RunReport | null>(null);
	let cases = $state<CaseResult[]>([]);
	let turns = $state<TurnRecord[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let caseFilter = $state('');
	let showPassed = $state(true);

	const runId = $derived(page.params.id ?? '');

	// `ok` and `duration_ms` are Python properties, not serialised fields, so
	// the UI derives them from the totals the report does carry.
	const runStatus = $derived(
		!report
			? null
			: report.totals.cases_errored || report.totals.cases_failed
				? 'failed'
				: 'passed'
	);

	async function load() {
		loading = true;
		try {
			[report, cases, turns] = await Promise.all([
				api.run(runId),
				api.runCases(runId),
				api.runTurns(runId)
			]);
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
			report = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void runId;
		void load();
	});

	const visibleCases = $derived(
		cases.filter((item) => {
			if (!showPassed && item.status === 'passed') return false;
			if (!caseFilter.trim()) return true;
			const needle = caseFilter.toLowerCase();
			return (
				item.name.toLowerCase().includes(needle) ||
				item.tags.some((tag) => tag.toLowerCase().includes(needle))
			);
		})
	);

	const failedCases = $derived(cases.filter((item) => item.status !== 'passed'));
	const failingTurns = $derived(
		turns.filter((turn) => turn.status !== 'passed' || turn.assertions.some((a) => !a.passed))
	);
</script>

<svelte:head><title>conversat — {runId}</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<div class="row">
			<h1>{report?.suite ?? runId}</h1>
			{#if report}<StatusBadge status={runStatus} />{/if}
		</div>
		{#if report}
			<p>
				<span class="mono">{report.run_id}</span> · started {dateTime(report.started_at)} ·
				connector <span class="mono">{report.connector}</span> · conversat v{report.version}
			</p>
		{:else}
			<p>Run detail</p>
		{/if}
	</div>
	<div class="row">
		<button class="ghost" onclick={() => goto('/runs')}>all runs</button>
		<button class="ghost" onclick={load} disabled={loading}>refresh</button>
	</div>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{:else if loading && !report}
	<div class="loading"><span class="spinner"></span>loading…</div>
{:else if report}
	{@const totals = report.totals}
	<div class="stack">
		<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))">
			<StatCard
				label="Cases"
				value="{totals.cases_passed}/{totals.cases}"
				hint="{totals.cases_failed} failed · {totals.cases_errored} errored"
				tone={totals.cases_failed || totals.cases_errored ? 'bad' : 'ok'}
			/>
			<StatCard
				label="Assertions"
				value="{totals.assertions_passed}/{totals.assertions}"
				tone={totals.assertions === totals.assertions_passed ? 'ok' : 'bad'}
			/>
			<StatCard label="Turns" value={count(totals.turns)} hint="{totals.turns_passed} passed" />
			<StatCard label="p50 response" value={duration(totals.response_p50_ms)} />
			<StatCard label="p95 response" value={duration(totals.response_p95_ms)} />
			<StatCard label="Wall clock" value={duration(totals.duration_ms)} />
		</div>

		{#if failingTurns.length}
			<details class="disclosure">
				<summary>
					<StatusBadge status="failed" />
					<strong>{failingTurns.length} failing turn{failingTurns.length === 1 ? '' : 's'}</strong>
					<span class="faint small">jump straight to what broke</span>
				</summary>
				<div class="disclosure-body">
					<div class="transcript">
						{#each failingTurns as turn (turn.suite + turn.case + turn.index)}
							<div>
								<div class="faint small mono" style="margin-bottom: 0.3rem">
									{turn.case} · <a href={`/cases/${encodeURIComponent(turn.case)}`}>history</a>
								</div>
								<Transcript {turn} />
							</div>
						{/each}
					</div>
				</div>
			</details>
		{/if}

		<div class="panel">
			<div class="panel-head">
				<h2>Cases</h2>
				<span class="faint small">{visibleCases.length} of {cases.length}</span>
				<div class="row">
					<label class="checkbox"><input type="checkbox" bind:checked={showPassed} /> show passing</label>
					<input placeholder="filter cases" bind:value={caseFilter} style="width: 160px" />
				</div>
			</div>
			<div class="panel-body">
				{#if !visibleCases.length}
					<p class="muted small">No cases match.</p>
				{:else}
					<div class="stack">
						{#each visibleCases as item (item.name)}
							<CaseTranscript result={item} />
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))">
			<div class="panel">
				<div class="panel-head"><h3>Environment</h3></div>
				<div class="panel-body">
					<dl class="kv">
						<dt>python</dt><dd>{String(report.environment.python ?? '—')}</dd>
						<dt>platform</dt><dd>{String(report.environment.platform ?? '—')}</dd>
						<dt>os</dt><dd>{String(report.environment.os ?? '—')}</dd>
						<dt>started</dt><dd>{dateTime(report.started_at)}</dd>
						<dt>finished</dt><dd>{dateTime(report.finished_at)}</dd>
						{#if report.labels.length}
							<dt>labels</dt>
							<dd>{report.labels.join(', ')}</dd>
						{/if}
					</dl>
				</div>
			</div>

			<div class="panel">
				<div class="panel-head"><h3>Totals</h3></div>
				<div class="panel-body">
					<dl class="kv">
						<dt>pass rate</dt>
						<dd>{percent(totals.cases ? (totals.cases_passed / totals.cases) * 100 : 0)}</dd>
						<dt>cases skipped</dt><dd>{count(totals.cases_skipped)}</dd>
						<dt>turns</dt><dd>{count(totals.turns)}</dd>
						<dt>failed cases</dt><dd>{failedCases.length ? failedCases.map((c) => c.name).join(', ') : 'none'}</dd>
					</dl>
				</div>
			</div>
		</div>
	</div>
{/if}