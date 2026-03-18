import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	css: {
		// Disable Vite's built-in PostCSS processing so it doesn't conflict
		// with @tailwindcss/vite (which handles CSS natively as a Vite plugin).
		// Without this, PostCSS auto-detects tailwindcss v4 in node_modules
		// and tries to run it as a v3 PostCSS plugin, causing @layer errors.
		postcss: {},
	},
	server: {
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true,
				configure: (proxy) => {
					proxy.on('proxyReq', (proxyReq) => {
						// Disable compression so SSE chunks arrive immediately
						proxyReq.setHeader('Accept-Encoding', 'identity');
					});
				}
			}
		}
	}
});
