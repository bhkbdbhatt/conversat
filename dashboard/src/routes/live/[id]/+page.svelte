<script lang="ts">
	import { page } from '$app/state';
	import { LiveRunView } from '$lib/live-state.svelte';
	import LiveBoard from '$lib/components/LiveBoard.svelte';

	const runId = $derived(page.params.id ?? '');
	const view = $state(new LiveRunView());

	$effect(() => {
		view.watch(runId);
		void view.refreshMeta();
		return () => view.stop();
	});
</script>

<svelte:head><title>conversat — live {runId}</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Live run</h1>
		<p>
			<span class="mono">{runId}</span> — each turn appears the moment the runner finishes it.
		</p>
	</div>
	<div class="row">
		<a class="button" href="/live">all live runs</a>
		<a class="button primary" href="/runs/{runId}">open report</a>
	</div>
</div>

<LiveBoard {view} />