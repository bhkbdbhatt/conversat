<script lang="ts">
	import { api } from '$lib/api';
	import { LiveRunView } from '$lib/live-state.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import LiveBoard from '$lib/components/LiveBoard.svelte';
	import RunLauncher from '$lib/components/RunLauncher.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { relativeTime } from '$lib/format';
	import type { LiveSnapshot, SuiteSummary } from '$lib/types';

	let active = $state<LiveSnapshot[]>([]);
	let suites = $state<SuiteSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	const view = $state(new LiveRunView());

	async function load() {
		loading = true;
		try {
			const [nextActive, nextSuites] = await Promise.all([api.activeRuns(), api.suites()]);
			active = nextActive;
			suites = nextSuites.suites;
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void load();
		// Poll while a run is in flight so the list appears the moment it starts.
		const timer = setInterval(() => void load(), 5_000);
		return () => clearInterval(timer);
	});

	$effect(() => {
		// Follow the newest in-flight run so this page is useful without an id.
		const first = active[0];
		if (first && !view.runId) view.watch(first.run_id);
		return () => view.stop();
	});
</script>

<svelte:head><title>conversat — live</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Live runs</h1>
		<p>Start a run here and watch every turn arrive over a WebSocket.</p>
	</div>
	<div class="row">
		<select
			aria-label="Run to follow"
			onchange={(event) => {
				const value = event.currentTarget.value;
				if (value) view.watch(value);
			}}
		>
			<option value="">follow the newest run…</option>
			{#each active as item (item.run_id)}
				<option value={item.run_id}>{item.suite} — {item.run_id}</option>
			{/each}
		</select>
		<button class="ghost" onclick={load} disabled={loading}>refresh</button>
	</div>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{/if}

<div class="stack">
	<RunLauncher {suites} onstarted={(ids) => ids.length === 1 && view.watch(ids[0])} />

	<div class="panel">
		<div class="panel-head">
			<h2>Stream</h2>
			{#if view.runId}
				<a class="button" href="/live/{view.runId}">open in its own view</a>
			{/if}
		</div>
		<div class="panel-body">
			<LiveBoard {view} />
		</div>
	</div>

	<div class="panel">
		<div class="panel-head">
			<h2>In flight</h2>
			<span class="faint small">{active.length} running</span>
		</div>
		<div class="panel-body flush">
			{#if loading && !active.length}
				<div class="loading"><span class="spinner"></span>loading…</div>
			{:else if !active.length}
				<EmptyState title="Nothing running" body="Start a run above and it will stream here." />
			{:else}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Suite</th>
								<th>Status</th>
								<th class="num">Cases</th>
								<th>Started</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each active as item (item.run_id)}
								<tr>
									<td>
										{item.suite}
										<div class="faint small mono">{item.run_id}</div>
									</td>
									<td><StatusBadge status={item.status} /></td>
									<td class="num">{item.cases?.length ?? 0}</td>
									<td class="nowrap">{relativeTime(item.started_at)}</td>
									<td class="right nowrap">
										<button class="ghost" onclick={() => view.watch(item.run_id)}>follow</button>
										<a class="button" href="/live/{item.run_id}">watch</a>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>
</div>