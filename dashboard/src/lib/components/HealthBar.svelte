<script lang="ts">
	import { count } from '$lib/format';
	import type { Health } from '$lib/types';

	let { health, offline }: { health: Health | null; offline: string | null } = $props();

	const live = $derived(health?.live.length ?? 0);
</script>

{#if offline}
	<span class="badge bad dot">offline</span>
{:else if health}
	<span class="badge muted dot" title={`reports dir: ${health.reports_dir}`}>
		{count(health.runs)} runs
	</span>
	<span class="badge muted dot" title={`suites dir: ${health.suites_dir}`}>
		{count(health.suites)} suites
	</span>
	{#if live}
		<span class="badge busy dot">{live} running</span>
	{/if}
	<span class="faint small mono">v{health.version}</span>
{/if}