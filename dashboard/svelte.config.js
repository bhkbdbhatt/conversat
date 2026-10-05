import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/**
 * The dashboard is a pure SPA: every byte of data comes from the conversat API
 * at runtime, so there is nothing to prerender. `fallback` lets FastAPI answer
 * any deep link (`/runs/abc`) with index.html and let the client router take
 * over -- that is what makes `conversat serve` the only command needed.
 *
 * @type {import('@sveltejs/kit').Config}
 */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: 'dist',
			assets: 'dist',
			fallback: 'index.html',
			precompress: false,
			strict: false
		}),
		alias: {
			$lib: 'src/lib'
		}
	}
};

export default config;