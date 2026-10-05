<script lang="ts">
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import { dateTime, duration, percent } from '$lib/format';
	import CrawlNode from '$lib/components/CrawlNode.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import type { CrawlTree } from '$lib/types';

	let crawl = $state<CrawlTree | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let onlyIssues = $state(false);

	const crawlId = $derived(page.params.id ?? '');

	async function load() {
		loading = true;
		try {
			crawl = await api.crawl(crawlId);
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void crawlId;
		void load();
	});

	const flagged = $derived(new Set((crawl?.issues ?? []).map((issue) => issue.node_id)));
	const coverage = $derived(crawl?.coverage ?? {});

	function visible(id: string, nodes: Record<string, { children: string[] }>): boolean {
		if (!onlyIssues) return true;
		const node = nodes[id];
		if (!node) return false;
		return flagged.has(id) || node.children.some((child) => visible(child, nodes));
	}
</script>

<svelte:head><title>conversat — {crawlId}</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>{crawl?.suite ?? crawlId}</h1>
		{#if crawl}
			<p>
				<span class="mono">{crawl.connector}</span> · crawled {dateTime(crawl.started_at)} ·
				{duration(crawl.duration_ms)} · {crawl.roots.length} root conversation(s)
			</p>
		{/if}
	</div>
	<div class="row">
		<label class="checkbox"><input type="checkbox" bind:checked={onlyIssues} /> only flagged branches</label>
		<button class="ghost" onclick={load} disabled={loading}>refresh</button>
	</div>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{:else if loading && !crawl}
	<div class="loading"><span class="spinner"></span>loading…</div>
{:else if crawl}
	<div class="stack">
		<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))">
			<StatCard label="Turns" value={String(coverage.nodes ?? 0)} />
			<StatCard label="Unique replies" value={String(coverage.unique_responses ?? 0)} />
			<StatCard label="Max depth" value={String(coverage.max_depth_reached ?? 0)} />
			<StatCard
				label="Empty replies"
				value={String(coverage.empty_responses ?? 0)}
				tone={coverage.empty_responses ? 'warn' : undefined}
			/>
			<StatCard label="p95" value={duration(Number(coverage.response_p95_ms ?? 0))} />
			<StatCard
				label="Error rate"
				value={percent(Number(crawl.coverage.error_rate ?? 0))}
				tone={Number(coverage.error_rate ?? 0) > 0 ? 'bad' : 'ok'}
			/>
		</div>

		<div class="panel">
			<div class="panel-head"><h2>Conversation tree</h2></div>
			<div class="panel-body">
				{#if !crawl.nodes || !Object.keys(crawl.nodes).length}
					<p class="muted small">The crawl produced no nodes.</p>
				{:else}
					<div class="tree">
						{#each crawl.roots as rootId (rootId)}
							{#if crawl.nodes[rootId] && visible(rootId, crawl.nodes)}
								<CrawlNode node={crawl.nodes[rootId]} nodes={crawl.nodes} />
							{/if}
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div class="panel">
			<div class="panel-head">
				<h2>Issues</h2>
				<span class="faint small">{crawl.issues.length} found</span>
			</div>
			<div class="panel-body flush">
				{#if !crawl.issues.length}
					<p class="muted small" style="padding: 0.9rem">No issues detected.</p>
				{:else}
					<div class="table-wrap">
						<table>
							<thead>
								<tr>
									<th>Kind</th>
									<th>Severity</th>
									<th class="num">Depth</th>
									<th>Message</th>
									<th>Exchange</th>
								</tr>
							</thead>
							<tbody>
								{#each crawl.issues as issue, i (i)}
									<tr>
										<td class="mono small">{issue.kind}</td>
										<td>
											<span
												class="badge"
												class:bad={issue.severity === 'error'}
												class:warn={issue.severity === 'warning'}
												class:muted={issue.severity === 'info'}
											>
												{issue.severity}
											</span>
										</td>
										<td class="num">{issue.depth}</td>
										<td class="small">{issue.message}</td>
										<td class="small mono">
											<div class="truncate">{issue.request}</div>
											<div class="truncate faint">{issue.response}</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>

		{#if crawl.suggested_cases.length}
			<details class="disclosure">
				<summary>
					<strong>{crawl.suggested_cases.length} suggested test case(s)</strong>
					<span class="faint small">generated from these transcripts — copy into a suite to keep them</span>
				</summary>
				<div class="disclosure-body">
					<pre>{JSON.stringify(crawl.suggested_cases, null, 2)}</pre>
				</div>
			</details>
		{/if}

		<details class="disclosure">
			<summary><span class="faint small">crawl config and generated suite</span></summary>
			<div class="disclosure-body stack">
				<pre>{JSON.stringify(crawl.config, null, 2)}</pre>
				<pre>{JSON.stringify(crawl.suite_yaml, null, 2)}</pre>
			</div>
		</details>
	</div>
{/if}