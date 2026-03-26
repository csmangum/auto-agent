/** Download a CSV file in the browser (UTF-8 with BOM for Excel). */
export function downloadCsv(filename: string, rows: string[][]): void {
  const escape = (cell: string) => {
    if (/[",\n\r]/.test(cell)) {
      return `"${cell.replace(/"/g, '""')}"`;
    }
    return cell;
  };
  const body = rows.map((r) => r.map((c) => escape(String(c))).join(',')).join('\r\n');
  const bom = '\uFEFF';
  const blob = new Blob([bom + body], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
