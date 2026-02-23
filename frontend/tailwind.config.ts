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
			},
			typography: (theme: (s: string) => string) => ({
				DEFAULT: {
					css: {
						color: '#cbd5e1',
						maxWidth: 'none',
						'h1, h2, h3, h4': {
							color: theme('colors.gold.DEFAULT'),
							fontFamily: 'Playfair Display, serif'
						},
						h1: { fontSize: '1.5rem' },
						h2: { fontSize: '1.25rem' },
						h3: { fontSize: '1.1rem' },
						a: { color: theme('colors.gold.light'), textDecoration: 'none' },
						'a:hover': { textDecoration: 'underline' },
						strong: { color: '#f1f5f9' },
						code: {
							color: theme('colors.gold.light'),
							backgroundColor: '#112548',
							padding: '0.1em 0.3em',
							borderRadius: '0.2em',
							fontSize: '0.85em'
						},
						'code::before': { content: '""' },
						'code::after': { content: '""' },
						pre: { backgroundColor: '#112548', border: '1px solid #1a3660' },
						hr: { borderColor: '#1a3660' },
						blockquote: {
							borderLeftColor: theme('colors.gold.dark'),
							color: '#94a3b8'
						},
						'ul > li::marker': { color: theme('colors.gold.muted') },
						'ol > li::marker': { color: theme('colors.gold.muted') },
						th: { color: theme('colors.gold.DEFAULT') },
						'thead tr': { borderBottomColor: '#1a3660' },
						'tbody tr': { borderBottomColor: '#112548' }
					}
				}
			})
		}
	},
	plugins: [typography]
} satisfies Config;
