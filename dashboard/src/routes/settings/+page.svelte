<script lang="ts">
	import { api } from '$lib/api';
	import { dateTime } from '$lib/format';
	import type { ConnectorInfo, Health } from '$lib/types';

	let health = $state<Health | null>(null);
	let connectors = $state<ConnectorInfo[]>([]);
	let assertions = $state<{ type: string }[]>([]);
	let error = $state<string | null>(null);

	async function load() {
		try {
			const [nextHealth, nextConnectors, nextAssertions] = await Promise.all([
				api.health(),
				api.connectors(),
				api.assertions()
			]);
			health = nextHealth;
			connectors = nextConnectors;
			assertions = nextAssertions;
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		}
	}

	$effect(() => {
		void load();
	});
</script>

<svelte:head><title>conversat — settings</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Settings</h1>
		<p>
			What this dashboard is pointed at, and the capabilities the server offers. There is nothing to
			authenticate -- conversat runs locally, as you.
		</p>
	</div>
	<button class="ghost" onclick={load}>refresh</button>
</div>

{#if error}
	<div class="notice bad">{error}</div>
{/if}

<div class="stack">
	<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))">
		<div class="panel">
			<div class="panel-head"><h2>Server</h2></div>
			<div class="panel-body">
				{#if health}
					<dl class="kv">
						<dt>version</dt><dd>{health.version}</dd>
						<dt>status</dt><dd>{health.status}</dd>
						<dt>reports dir</dt><dd>{health.reports_dir}</dd>
						<dt>suites dir</dt><dd>{health.suites_dir}</dd>
						<dt>runs loaded</dt><dd>{health.runs}</dd>
						<dt>crawls loaded</dt><dd>{health.crawls}</dd>
						<dt>suites found</dt><dd>{health.suites}</dd>
						<dt>web UI</dt>
						<dd>
							{health.ui ? 'built and served from this process' : 'API only — run npm --prefix dashboard run build'}
						</dd>
					</dl>
					<hr />
					<p class="small muted" style="margin: 0">
						Point the server elsewhere with
						<code>conversat serve --reports &lt;dir&gt; --suites &lt;dir&gt;</code>. Restart it for
						changes to apply.
					</p>
				{:else}
					<div class="loading"><span class="spinner"></span>loading…</div>
				{/if}
			</div>
		</div>

		<div class="panel">
			<div class="panel-head">
				<h2>Assertion strategies</h2>
				<span class="faint small">{assertions.length}</span>
			</div>
			<div class="panel-body">
				<p class="small muted" style="margin-top: 0">
					Use these as shorthand keys in a suite's <code>expect:</code> list.
				</p>
				<div class="chips">
					{#each assertions as item (item.type)}
						<span class="tag">{item.type}</span>
					{/each}
				</div>
			</div>
		</div>
	</div>

	<div class="panel">
		<div class="panel-head">
			<h2>Connectors</h2>
			<span class="faint small">{connectors.length} built in</span>
		</div>
		<div class="panel-body flush">
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Type</th>
							<th>What it drives</th>
							<th>Config keys</th>
						</tr>
					</thead>
					<tbody>
						{#each connectors as connector (connector.type)}
							<tr>
								<td class="mono"><strong>{connector.type}</strong></td>
								<td class="small muted">{connector.description}</td>
								<td>
									<div class="chips">
										{#each Object.keys(connector.defaults ?? {}) as key (key)}
											<span class="tag">{key}</span>
										{/each}
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<div class="panel">
		<div class="panel-head"><h2>LLM settings</h2></div>
		<div class="panel-body">
			<div class="notice warn">
				Not implemented yet. Judge-based grading (<code>conversat eval</code>) and
				<code>conversat redteam</code> are on the roadmap; until then no API keys are needed
				or stored.
			</div>
		</div>
	</div>
</div>