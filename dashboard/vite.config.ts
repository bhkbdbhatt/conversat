import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// The dev server talks to `conversat serve`; the built app is served by that
// same process, so both paths hit the same relative /api and /ws URLs.
const API_TARGET = process.env.CONVERSAT_API ?? 'http://127.0.0.1:8080';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5173,
		strictPort: false,
		proxy: {
			'/api': { target: API_TARGET, changeOrigin: true },
			'/ws': { target: API_TARGET, ws: true, changeOrigin: true }
		}
	}
});