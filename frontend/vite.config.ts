import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
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
