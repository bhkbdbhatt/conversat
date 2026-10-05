<script lang="ts">
	import { goto } from '$app/navigation';
	import SuiteEditor from '$lib/components/SuiteEditor.svelte';
</script>

<svelte:head><title>conversat — new suite</title></svelte:head>

<SuiteEditor
	onsaved={(saved) => {
		if (saved) void goto(`/suites/${encodeURIComponent(saved.name)}`);
	}}
/>