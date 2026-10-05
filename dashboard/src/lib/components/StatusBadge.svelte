<script lang="ts">
	import { statusTone } from '$lib/format';

	let {
		status,
		label
	}: {
		status: string | null | undefined;
		label?: string | null;
	} = $props();

	const tone = $derived(statusTone(status ?? undefined));
</script>

<span class="badge {tone} dot">{label ?? status ?? 'unknown'}</span>