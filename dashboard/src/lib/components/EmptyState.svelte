<script lang="ts">
	let {
		title = 'Nothing here yet',
		body,
		action,
		actionText = 'Refresh',
		href,
		linkText
	}: {
		title?: string;
		body?: string;
		action?: () => void;
		actionText?: string;
		href?: string;
		linkText?: string;
	} = $props();
</script>

<div class="empty">
	<h3>{title}</h3>
	{#if body}<p>{body}</p>{/if}
	{#if action}
		<button onclick={action}>{actionText}</button>
	{:else if href && linkText}
		<a class="button" {href}>{linkText}</a>
	{/if}
</div>