<script lang="ts">
	import { untrack } from 'svelte';
	import { api } from '$lib/api';

	const TEMPLATE = `name: my-bot
description: Smoke tests for the support bot

connector:
  type: http
  config:
    url: http://127.0.0.1:8099/chat
    response_text_path: reply

defaults:
  tags: [smoke]
  timeout: 15

cases:
  - name: greets the user
    tags: [chat]
    steps:
      - send: Hello!
        expect:
          - not_empty: true
          - contains_any: [hello, hi, hey]
          - latency_under: 5000

      - send: What is 2 + 2?
        expect:
          - contains: "4"
`;

	let {
		name = null,
		initialYaml = TEMPLATE,
		onsaved
	}: {
		/** ``null`` creates a new suite. */
		name?: string | null;
		initialYaml?: string;
		onsaved?: (saved: { name: string; path?: string } | null) => void;
	} = $props();

	// `untrack` is deliberate: the editor seeds itself from the prop once, and
	// from then on the textarea -- not the prop -- is the source of truth.
	let text = $state(untrack(() => initialYaml ?? TEMPLATE));
	let saving = $state(false);
	let saved = $state(false);
	let error = $state<string | null>(null);
	let check = $state<{ valid: boolean; errors: string[]; cases: string[] } | null>(null);
	let checking = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function validate() {
		if (!text.trim()) {
			check = null;
			return;
		}
		checking = true;
		try {
			check = await api.validateYaml(text);
			error = null;
		} catch (cause) {
			check = null;
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			checking = false;
		}
	}

	function schedule() {
		saved = false;
		if (timer) clearTimeout(timer);
		timer = setTimeout(() => void validate(), 450);
	}

	async function save() {
		saving = true;
		error = null;
		try {
			const result = await api.saveYaml(text, name ?? undefined);
			onsaved?.(result);
			saved = true;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			saving = false;
		}
	}

	async function remove() {
		if (!name || !confirm(`Delete suite "${name}"? The YAML file is removed from disk.`)) return;
		saving = true;
		try {
			await api.deleteSuite(name);
			onsaved?.(null);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			saving = false;
		}
	}

	function useTemplate() {
		if (text.trim() && !confirm('Replace the editor contents with the starter template?')) return;
		text = TEMPLATE;
		schedule();
	}

	$effect(() => {
		void validate();
		return () => {
			if (timer) clearTimeout(timer);
		};
	});
</script>

<div class="page-head">
	<div class="grow">
		<h1>{name ? `Edit ${name}` : 'New suite'}</h1>
		<p>
			Suites are plain YAML. The server validates on every keystroke and writes the file back on save,
			so <code>conversat run</code> can execute it unchanged.
		</p>
	</div>
	<div class="row">
		{#if name}
			<button class="danger" onclick={remove} disabled={saving}>delete</button>
		{/if}
		<button class="ghost" onclick={useTemplate}>starter template</button>
		<button class="primary" onclick={save} disabled={saving || !check?.valid}>
			<span class:spinner={saving}></span>
			{saving ? 'Saving…' : 'Save suite'}
		</button>
	</div>
</div>

<div class="grid" style="grid-template-columns: minmax(0, 3fr) minmax(240px, 1fr); align-items: start">
	<div class="panel">
		<div class="panel-head">
			<h2>YAML</h2>
			{#if checking}
				<span class="faint small">checking…</span>
			{:else if check?.valid}
				<span class="badge ok dot">valid · {check.cases.length} case(s)</span>
			{:else if check}
				<span class="badge bad dot">invalid</span>
			{/if}
			<span class="grow" style="flex: 1"></span>
			{#if saved}
				<span class="badge ok dot">saved</span>
			{/if}
		</div>
		<div class="panel-body">
			<textarea
				bind:value={text}
				oninput={schedule}
				spellcheck="false"
				rows="26"
				aria-label="Suite YAML"
			></textarea>
		</div>
	</div>

	<div class="stack">
		{#if error}
			<div class="notice bad">{error}</div>
		{/if}

		{#if check && !check.valid}
			<div class="panel">
				<div class="panel-head"><h3>Problems</h3></div>
				<div class="panel-body">
					<ul style="margin: 0; padding-left: 1.1rem" class="small">
						{#each check.errors as problem, i (i)}
							<li>{problem}</li>
						{/each}
					</ul>
				</div>
			</div>
		{/if}

		{#if check?.valid}
			<div class="panel">
				<div class="panel-head"><h3>Cases</h3></div>
				<div class="panel-body flush">
					<table>
						<tbody>
							{#each check.cases as caseName, i (i)}
								<tr>
									<td>{i + 1}</td>
									<td>{caseName}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<div class="panel">
			<div class="panel-head"><h3>Tips</h3></div>
			<div class="panel-body small muted stack">
				<p style="margin: 0">
					<code>expect:</code> takes assertion shorthands — <code>contains: hello</code>,
					<code>contains_any: [a, b]</code>, <code>matches: "\\d+"</code>,
					<code>latency_under: 2000</code>, or the long form with
					<code>type:</code> plus its fields.
				</p>
				<p style="margin: 0">
					<code>setup:</code> runs before <code>steps:</code>, and inherits
					<code>defaults:</code>. Tags in <code>defaults.tags</code> apply to every case.
				</p>
				<p style="margin: 0">
					Run <code>conversat init</code> in a terminal to scaffold a file-based suite
					instead.
				</p>
			</div>
		</div>
	</div>
</div>

<style>
	textarea {
		min-height: 32rem;
	}
</style>