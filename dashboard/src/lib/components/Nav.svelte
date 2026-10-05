<script lang="ts">
	import { page } from '$app/state';

	const links = [
		{ href: '/', label: 'Overview' },
		{ href: '/runs', label: 'Runs' },
		{ href: '/suites', label: 'Suites' },
		{ href: '/suites/import', label: 'Import', exact: true },
		{ href: '/crawl', label: 'Crawl' },
		{ href: '/live', label: 'Live' },
		{ href: '/settings', label: 'Settings' }
	];

	function isActive(href: string, exact = false): boolean {
		const path = page.url.pathname;
		if (href === '/') return path === '/';
		return exact ? path === href : path === href || path.startsWith(`${href}/`);
	}
</script>

<nav class="nav">
	{#each links as link (link.href)}
		<a href={link.href} class:active={isActive(link.href, link.exact)}>{link.label}</a>
	{/each}
</nav>