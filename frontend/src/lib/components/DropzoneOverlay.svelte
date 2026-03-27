<script lang="ts">
	let { visible = false, rejected = false }: { visible: boolean; rejected?: boolean } = $props();
</script>

{#if visible}
	<div
		class="absolute inset-0 z-40 flex items-center justify-center
		       border-2 rounded-lg backdrop-blur-sm transition-colors
		       {rejected
			       ? 'border-red-500/60 bg-navy-900/80'
			       : 'border-gold/60 bg-navy-900/80'}"
		role="region"
		aria-label="File drop zone"
		aria-live="assertive"
	>
		<div class="flex flex-col items-center gap-3 pointer-events-none select-none">
			{#if rejected}
				<!-- X / rejection icon -->
				<svg
					class="w-10 h-10 text-red-400"
					aria-hidden="true"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<circle cx="12" cy="12" r="10" stroke-width="1.5" />
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 9l-6 6M9 9l6 6" />
				</svg>
				<p class="text-sm font-medium text-red-400">Unsupported file type</p>
			{:else}
				<!-- Upload arrow icon -->
				<svg
					class="w-10 h-10 text-gold motion-safe:animate-bounce"
					aria-hidden="true"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1.5"
						d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
					/>
				</svg>
				<p class="text-sm font-medium text-gold">Drop to attach</p>
			{/if}
		</div>
	</div>
{/if}
