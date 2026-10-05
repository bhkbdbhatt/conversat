<script lang="ts">
	import { api } from '$lib/api';
	import { pluralise } from '$lib/format';
	import type { RunOptions, SuiteSummary } from '$lib/types';

	let {
		suites,
		preselected = '',
		onstarted
	}: {
		suites: SuiteSummary[];
		preselected?: string;
		onstarted?: (runIds: string[]) => void;
	} = $props();

	let selected = $state<string[]>([]);
	let concurrency = $state(4);
	let tags = $state('');
	let caseNames = $state('');
	let failFast = $state(false);
	let dryRun = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);

	// Preselect when the caller passes a suite, but let the user change it.
	$effect(() => {
		selected = preselected ? [preselected] : [];
	});

	const usable = $derived(suites.filter((suite) => !suite.error));
	const broken = $derived(suites.filter((suite) => suite.error));

	function toggle(name: string) {
		selected = selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name];
	}

	function splitList(value: string): string[] {
		return value
			.split(/[,\s]+/)
			.map((item) => item.trim())
			.filter(Boolean);
	}

	async function start() {
		if (!selected.length) return;
		busy = true;
		error = null;
		const options: RunOptions = {
			concurrency: Number(concurrency) || 1,
			fail_fast: failFast,
			dry_run: dryRun,
			tags: splitList(tags),
			cases: splitList(caseNames)
		};
		try {
			const response = await api.startRun(selected, options);
			onstarted?.(response.started.map((item) => item.run_id));
			selected = [];
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}
</script>

<div class="panel">
	<div class="panel-head">
		<h3>Run a suite</h3>
		{#if selected.length}
			<span class="badge muted">{pluralise(selected.length, 'suite')} selected</span>
		{/if}
	</div>
	<div class="panel-body">
		{#if !usable.length}
			<p class="muted small">
				No runnable suites found. Point the server at a directory of YAML suites with
				<code>conversat serve --suites &lt;dir&gt;</code>, or add one below.
			</p>
		{:else}
			<div class="chips" style="margin-bottom: 0.85rem">
				{#each usable as suite (suite.path + suite.document)}
					<button
						class="tag"
						style:background={selected.includes(suite.name) ? 'var(--accent)' : undefined}
						style:color={selected.includes(suite.name) ? 'var(--accent-ink)' : undefined}
						style:border-color={selected.includes(suite.name) ? 'var(--accent)' : undefined}
						onclick={() => toggle(suite.name)}
						title={suite.description ?? suite.path}
					>
						{suite.name}
						<span class="faint">· {suite.cases} cases</span>
					</button>
				{/each}
			</div>

			<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))">
				<div class="field">
					<label for="run-concurrency">Concurrency</label>
					<input id="run-concurrency" type="number" min="1" max="32" bind:value={concurrency} />
				</div>
				<div class="field">
					<label for="run-tags">Only tags (comma separated)</label>
					<input id="run-tags" placeholder="smoke, fast" bind:value={tags} />
				</div>
				<div class="field">
					<label for="run-cases">Only cases</label>
					<input id="run-cases" placeholder="greeting, memory" bind:value={caseNames} />
				</div>
			</div>

			<div class="row" style="margin-bottom: 0.85rem">
				<label class="checkbox"><input type="checkbox" bind:checked={failFast} /> fail fast</label>
				<label class="checkbox"><input type="checkbox" bind:checked={dryRun} /> dry run (no bot calls)</label>
			</div>

			<div class="row">
				<button class="primary" onclick={start} disabled={busy || !selected.length}>
					<span class:spinner={busy}></span>
					{busy ? 'Starting…' : `Run ${selected.length ? selected.join(', ') : ''}`}
				</button>
				{#if selected.length}
					<button class="ghost" onclick={() => (selected = [])}>clear</button>
				{/if}
			</div>
		{/if}

		{#if error}
			<div class="notice bad" style="margin-top: 0.85rem">{error}</div>
		{/if}

		{#if broken.length}
			<details style="margin-top: 0.85rem">
				<summary class="small muted">{pluralise(broken.length, 'unreadable suite')} — click for errors</summary>
				{#each broken as suite (suite.path)}
					<div class="notice bad" style="margin-top: 0.5rem">
						<strong>{suite.name}</strong> <span class="faint">{suite.path}</span>
						<pre style="margin-top: 0.35rem; white-space: pre-wrap">{suite.error}</pre>
					</div>
				{/each}
			</details>
		{/if}
	</div>
</div>