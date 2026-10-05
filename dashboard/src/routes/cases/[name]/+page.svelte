<script lang="ts">
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { dateTime, duration, pluralise, relativeTime } from '$lib/format';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Transcript from '$lib/components/Transcript.svelte';
	import type { CaseHistory } from '$lib/types';

	let history = $state<CaseHistory[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const name = $derived(page.params.name ?? '');

	async function load() {
		loading = true;
		try {
			history = await api.caseHistory(name);
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
			history = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void name;
		void load();
	});

	const latest = $derived(history.at(-1));
</script>

<svelte:head><title>conversat — {name}</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>{name}</h1>
		<p>
			Every recorded run of this case, oldest first — the quickest way to spot a regression.
		</p>
	</div>
	<button class="ghost" onclick={load} disabled={loading}>refresh</button>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{:else if loading && !history.length}
	<div class="loading"><span class="spinner"></span>loading…</div>
{:else if !history.length}
	<EmptyState title="No history for this case" body="It has not run in any report on this machine." />
{:else}
	<div class="stack">
		{#if latest}
			<div class="panel">
				<div class="panel-head">
					<h2>Latest transcript</h2>
					<StatusBadge status={latest.status} />
					<span class="faint small">
						{latest.run_id} · {dateTime(latest.started_at)} · {duration(latest.duration_ms)}
					</span>
				</div>
				<div class="panel-body">
					{#if latest.error}
						<div class="notice bad" style="margin-bottom: 0.75rem">{latest.error}</div>
					{/if}
					<div class="transcript">
						{#each latest.turn_rows as turn (turn.index)}
							<Transcript {turn} />
						{/each}
					</div>
				</div>
			</div>
		{/if}

		<div class="panel">
			<div class="panel-head">
				<h2>Run history</h2>
				<span class="faint small">{pluralise(history.length, 'run')}</span>
			</div>
			<div class="panel-body flush">
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Run</th>
								<th>Status</th>
								<th class="num">Turns</th>
								<th class="num">Assertions</th>
								<th class="num">Failed</th>
								<th class="num">Duration</th>
								<th>Started</th>
							</tr>
						</thead>
						<tbody>
							{#each history as row (row.run_id)}
								<tr>
									<td><a href="/runs/{row.run_id}" class="mono small">{row.run_id}</a></td>
									<td><StatusBadge status={row.status} /></td>
									<td class="num">{row.turns}</td>
									<td class="num">{row.assertions}</td>
									<td class="num" style:color={row.failed_assertions ? 'var(--bad)' : undefined}>
										{row.failed_assertions}
									</td>
									<td class="num">{duration(row.duration_ms)}</td>
									<td class="nowrap" title={dateTime(row.started_at)}>{relativeTime(row.started_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
{/if}