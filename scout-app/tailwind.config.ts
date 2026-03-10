import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';

export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			colors: {
				navy: {
					DEFAULT: '#0a1628',
					900: '#060e1a',
					800: '#0d1e38',
					700: '#112548',
					600: '#1a3660',
					500: '#254d85'
				},
				gold: {
					DEFAULT: '#c9a84c',
					light: '#e4c97e',
					dark: '#a0802a',
					muted: '#8a6d2a'
				}
			},
			fontFamily: {
				serif: ['Playfair Display', 'Georgia', 'serif'],
				sans: ['Inter', 'system-ui', 'sans-serif']
			}
		}
	},
	plugins: [typography]
} satisfies Config;
