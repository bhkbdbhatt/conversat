<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import SuiteEditor from '$lib/components/SuiteEditor.svelte';
	import type { SuitePayload } from '$lib/types';

	let name = $derived(page.params.name ?? '');
	let suite = $state<SuitePayload | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		try {
			suite = await api.suite(name);
			error = null;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void name;
		void load();
	});
</script>

<svelte:head><title>conversat — {name}</title></svelte:head>

{#if error}
	<div class="notice bad">{error}</div>
	<div class="row" style="margin-top: 0.75rem">
		<a class="button" href="/suites">back to suites</a>
	</div>
{:else if loading || !suite}
	<div class="loading"><span class="spinner"></span>loading {name}…</div>
{:else}
	<SuiteEditor
		name={suite.name}
		initialYaml={suite.yaml ?? ''}
		onsaved={(saved) => {
			if (!saved) void goto('/suites');
		}}
	/>
{/if}