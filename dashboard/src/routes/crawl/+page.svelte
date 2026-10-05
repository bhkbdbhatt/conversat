<script lang="ts">
	import { api } from '$lib/api';
	import { dateTime, percent, relativeTime } from '$lib/format';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import type { CrawlSummary } from '$lib/types';

	let crawls = $state<CrawlSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		try {
			crawls = await api.crawls();
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
</script>

<svelte:head><title>conversat — crawl</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Crawl</h1>
		<p>
			Exploration reports written by <code class="mono">conversat crawl --json</code>. Each one maps every
			reply the bot gave, so you can spot dead ends and missing coverage.
		</p>
	</div>
	<button class="ghost" onclick={load} disabled={loading}>refresh</button>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{/if}

<div class="panel">
	<div class="panel-body flush">
		{#if loading && !crawls.length}
			<div class="loading"><span class="spinner"></span>loading…</div>
		{:else if !crawls.length}
			<EmptyState
				title="No crawl reports"
				body="Explore a bot from the terminal, for example: `conversat crawl --suite examples/suites/http.yaml --json --output reports/crawl-demo.json`."
			/>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Crawl</th>
							<th>Connector</th>
							<th class="num">Turns</th>
							<th class="num">Depth</th>
							<th class="num">Unique replies</th>
							<th class="num">Errors</th>
							<th class="num">Error rate</th>
							<th class="num">Issues</th>
							<th class="num">Cases</th>
							<th>Started</th>
						</tr>
					</thead>
					<tbody>
						{#each crawls as crawl (crawl.crawl_id)}
							<tr>
								<td>
									<a href="/crawl/{encodeURIComponent(crawl.crawl_id)}">{crawl.crawl_id}</a>
									<div class="faint small">{crawl.suite}</div>
								</td>
								<td class="mono small">{crawl.connector}</td>
								<td class="num">{crawl.nodes}</td>
								<td class="num">{crawl.max_depth}</td>
								<td class="num">{crawl.unique_responses}</td>
								<td class="num" style:color={crawl.error_rate > 0 ? 'var(--bad)' : undefined}>
									{percent(crawl.error_rate * 100)}
								</td>
								<td class="num">{crawl.issues}</td>
								<td class="num">{crawl.suggested_cases}</td>
								<td class="nowrap" title={dateTime(crawl.started_at)}>{relativeTime(crawl.started_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>