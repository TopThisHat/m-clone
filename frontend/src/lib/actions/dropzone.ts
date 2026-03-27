export interface DropzoneOptions {
	onEnter?: () => void;
	onLeave?: () => void;
	onDrop: (files: File[]) => void;
	disabled?: boolean;
}

/**
 * Svelte action that turns any element into a drag-and-drop file target.
 * Uses enterCount ref-counting so nested child enter/leave events don't
 * spuriously fire onLeave while the pointer is still over the zone.
 */
export function dropzone(node: HTMLElement, options: DropzoneOptions) {
	let opts = options;
	let enterCount = 0;

	function hasFiles(e: DragEvent): boolean {
		if (!e.dataTransfer) return false;
		// Safari exposes DOMStringList, not a plain array — use Array.from
		return Array.from(e.dataTransfer.types).includes('Files');
	}

	function handleDragEnter(e: DragEvent) {
		if (opts.disabled || !hasFiles(e)) return;
		e.preventDefault();
		enterCount++;
		if (enterCount === 1) opts.onEnter?.();
	}

	function handleDragOver(e: DragEvent) {
		if (opts.disabled || !hasFiles(e)) return;
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
	}

	function handleDragLeave(e: DragEvent) {
		if (opts.disabled || !hasFiles(e)) return;
		e.preventDefault();
		enterCount = Math.max(0, enterCount - 1);
		if (enterCount === 0) opts.onLeave?.();
	}

	function handleDrop(e: DragEvent) {
		if (opts.disabled) return;
		e.preventDefault();
		enterCount = 0;
		opts.onLeave?.();
		const files = e.dataTransfer?.files ? Array.from(e.dataTransfer.files) : [];
		if (files.length > 0) opts.onDrop(files);
	}

	node.addEventListener('dragenter', handleDragEnter);
	node.addEventListener('dragover', handleDragOver);
	node.addEventListener('dragleave', handleDragLeave);
	node.addEventListener('drop', handleDrop);

	return {
		update(newOptions: DropzoneOptions) {
			opts = newOptions;
		},
		destroy() {
			node.removeEventListener('dragenter', handleDragEnter);
			node.removeEventListener('dragover', handleDragOver);
			node.removeEventListener('dragleave', handleDragLeave);
			node.removeEventListener('drop', handleDrop);
		}
	};
}
