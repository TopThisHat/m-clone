import { defineConfig, devices } from '@playwright/test';

const TEST_PORT = process.env.CI ? 5173 : 5174;

export default defineConfig({
	testDir: './e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 1 : undefined,
	reporter: 'html',
	use: {
		baseURL: `http://localhost:${TEST_PORT}`,
		trace: 'on-first-retry',
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] },
		},
		{
			name: 'mobile',
			use: { ...devices['Pixel 5'] },
		},
	],
	webServer: [
		{
			command: 'npx tsx e2e/mock-api-server.ts',
			url: 'http://localhost:8001/health',
			reuseExistingServer: !process.env.CI,
		},
		{
			command: `npx vite dev --port ${TEST_PORT}`,
			url: `http://localhost:${TEST_PORT}`,
			reuseExistingServer: !process.env.CI,
			env: { API_TARGET: 'http://localhost:8001' },
		},
	],
});
