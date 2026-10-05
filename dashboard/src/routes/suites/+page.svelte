<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { dateTime, pluralise, relativeTime } from '$lib/format';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import RunLauncher from '$lib/components/RunLauncher.svelte';
	import type { SuiteSummary } from '$lib/types';

	let directory = $state('');
	let suites = $state<SuiteSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let filter = $state('');

	async function load() {
		loading = true;
		try {
			const response = await api.suites();
			directory = response.directory;
			suites = response.suites;
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

	const visible = $derived(
		suites.filter((suite) =>
			filter.trim()
				? suite.name.toLowerCase().includes(filter.trim().toLowerCase()) ||
					(suite.tags ?? []).some((tag) => tag.includes(filter.trim().toLowerCase()))
				: true
		)
	);
</script>

<svelte:head><title>conversat — suites</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Suites</h1>
		<p>
			YAML suites in <code class="mono">{directory || '…'}</code> — the same files
			<code class="mono">conversat run</code> reads.
		</p>
	</div>
	<div class="row">
		<input placeholder="filter" bind:value={filter} style="width: 160px" />
		<a class="button primary" href="/suites/import">import conversation</a>
		<a class="button" href="/suites/new">new suite</a>
		<button class="ghost" onclick={load} disabled={loading}>refresh</button>
	</div>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{/if}

<div class="stack">
		<RunLauncher
			{suites}
			onstarted={(ids) => {
				if (ids.length === 1) void goto(`/live/${ids[0]}`);
			}}
		/>

	<div class="panel">
		<div class="panel-head">
			<h2>Available suites</h2>
			<span class="faint small">{pluralise(suites.length, 'file')}</span>
		</div>
		<div class="panel-body flush">
			{#if loading && !suites.length}
				<div class="loading"><span class="spinner"></span>loading…</div>
			{:else if !suites.length}
				<EmptyState
					title="No suites in this directory"
					body="Point the server at your suites with `conversat serve --suites <dir>`, or create one here."
					href="/suites/new"
					linkText="Create a suite"
				/>
			{:else if !visible.length}
				<EmptyState title="No matches" body="Nothing matches that filter." />
			{:else}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Name</th>
								<th>Connector</th>
								<th class="num">Cases</th>
								<th class="num">Turns</th>
								<th class="num">Assertions</th>
								<th>Tags</th>
								<th>Modified</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each visible as suite (suite.path + suite.document)}
								{#if suite.error}
									<tr>
										<td><strong>{suite.name}</strong></td>
										<td colspan="5">
											<div class="notice bad small">{suite.error}</div>
										</td>
										<td class="nowrap faint small">{relativeTime(suite.modified)}</td>
										<td></td>
									</tr>
								{:else}
									<tr>
										<td>
											<a href="/suites/{encodeURIComponent(suite.name)}">{suite.name}</a>
											<div class="faint small mono">{suite.path}</div>
											{#if suite.description}
												<div class="faint small">{suite.description}</div>
											{/if}
										</td>
										<td class="mono small">{suite.connector}</td>
										<td class="num">{suite.cases}</td>
										<td class="num">{suite.turns}</td>
										<td class="num">{suite.assertions}</td>
										<td>
											<div class="chips">
												{#each suite.tags ?? [] as tag (tag)}
													<span class="tag">{tag}</span>
												{/each}
											</div>
										</td>
										<td class="nowrap" title={dateTime(suite.modified ?? null)}>{relativeTime(suite.modified)}</td>
										<td class="right nowrap">
											<a class="button" href="/suites/{encodeURIComponent(suite.name)}">edit</a>
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>
</div>