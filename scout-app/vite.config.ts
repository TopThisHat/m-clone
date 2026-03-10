import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5174,
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true,
				configure: (proxy) => {
					proxy.on('proxyReq', (proxyReq) => {
						proxyReq.setHeader('Accept-Encoding', 'identity');
					});
				}
			}
		}
	}
});
