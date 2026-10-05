<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import Nav from '$lib/components/Nav.svelte';
	import HealthBar from '$lib/components/HealthBar.svelte';
	import { api } from '$lib/api';
	import type { Health } from '$lib/types';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	let health = $state<Health | null>(null);
	let offline = $state<string | null>(null);

	async function refresh() {
		try {
			health = await api.health();
			offline = null;
		} catch (error) {
			offline = error instanceof Error ? error.message : String(error);
			health = null;
		}
	}

	$effect(() => {
		void refresh();
		const timer = setInterval(() => void refresh(), 15_000);
		return () => clearInterval(timer);
	});

	// A run finishing anywhere in the app should refresh the header counters.
	$effect(() => {
		void page.url.pathname;
		void refresh();
	});
</script>

<div class="shell">
	<header class="topbar">
		<span class="brand">conversat <small>dashboard</small></span>
		<Nav />
		<div class="topbar-end">
			<HealthBar {health} {offline} />
		</div>
	</header>

	{#if offline}
		<div class="notice bad" style="margin: 0.75rem 1.25rem 0">
			{offline}
		</div>
	{/if}

	<main class="main">
		{@render children()}
	</main>
</div>