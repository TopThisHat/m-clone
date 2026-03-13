async function doExport(table: HTMLTableElement, name: string) {
	const XLSX = await import('xlsx');
	const wb = XLSX.utils.book_new();
	const ws = XLSX.utils.table_to_sheet(table);
	XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
	XLSX.writeFile(wb, `${name}.xlsx`);
}

export function injectButtons(node: HTMLElement) {
	node.querySelectorAll('table').forEach((table, idx) => {
		if (table.closest('.tbl-export-wrap')) return;
		const wrapper = document.createElement('div');
		wrapper.className = 'tbl-export-wrap relative my-4 overflow-x-auto';
		const btn = document.createElement('button');
		btn.className =
			'absolute top-1 right-1 z-10 text-[10px] px-2 py-0.5 rounded border border-navy-600 bg-navy-800 text-slate-400 hover:text-gold hover:border-gold/40 transition-colors';
		btn.title = 'Export as Excel';
		btn.textContent = '↓ Excel';
		btn.type = 'button';
		btn.addEventListener('click', (e) => {
			e.stopPropagation();
			doExport(table as HTMLTableElement, `table-${idx + 1}`);
		});
		table.parentNode!.insertBefore(wrapper, table);
		wrapper.appendChild(btn);
		wrapper.appendChild(table);
	});
}

export function tableExport(node: HTMLElement) {
	injectButtons(node);
	return {
		update() {
			// Re-wrap any new tables added after an html update
			injectButtons(node);
		}
	};
}
