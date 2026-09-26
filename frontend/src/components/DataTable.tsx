import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Search, SlidersHorizontal } from 'lucide-react';

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  // Plain text used for search matching. Defaults to render() output when omitted.
  searchValue?: (row: T) => string;
  // Columns default to visible; set false to start hidden (e.g. rarely-needed detail columns).
  defaultVisible?: boolean;
  align?: 'left' | 'right' | 'center';
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowId: (row: T) => string | number;
  actions?: (row: T) => React.ReactNode;
  emptyMessage?: string;
  searchPlaceholder?: string;
  // Persists column visibility / page size per table across visits.
  storageKey?: string;
}

const PAGE_SIZES = [25, 50, 100];

// Tailwind's build scans for literal class strings, so alignment classes
// must be spelled out in full rather than built with a template literal.
const ALIGN_CLASS: Record<'left' | 'right' | 'center', string> = {
  left: 'text-left', right: 'text-right', center: 'text-center',
};

/** One reusable table for every list page: search, column visibility, page
 * size, a sticky header, and a row-actions slot (Phase 3.4/3.10 - one table
 * component instead of a bespoke <table> on every page). */
export function DataTable<T>({
  columns, rows, getRowId, actions, emptyMessage = 'Nothing here yet.',
  searchPlaceholder = 'Search...', storageKey,
}: DataTableProps<T>) {
  const storage = storageKey ? `datatable:${storageKey}` : null;

  const [search, setSearch] = useState('');
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [page, setPage] = useState(1);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(() => {
    const initiallyHidden = columns.filter((c) => c.defaultVisible === false).map((c) => c.key);
    if (!storage) return new Set(initiallyHidden);
    try {
      const saved = localStorage.getItem(storage);
      return saved ? new Set(JSON.parse(saved)) : new Set(initiallyHidden);
    } catch {
      return new Set(initiallyHidden);
    }
  });

  useEffect(() => {
    if (!storage) return;
    try { localStorage.setItem(storage, JSON.stringify([...hiddenColumns])); } catch { /* private-mode storage - ignore */ }
  }, [hiddenColumns, storage]);

  useEffect(() => { setPage(1); }, [search, pageSize]);

  const visibleColumns = columns.filter((c) => !hiddenColumns.has(c.key));

  const filteredRows = useMemo(() => {
    if (!search.trim()) return rows;
    const needle = search.trim().toLowerCase();
    return rows.filter((row) =>
      columns.some((col) => (col.searchValue ? col.searchValue(row) : String(col.render(row) ?? '')).toLowerCase().includes(needle))
    );
  }, [rows, search, columns]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = filteredRows.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const toggleColumn = (key: string) => {
    setHiddenColumns((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <select
          value={pageSize}
          onChange={(e) => setPageSize(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
          aria-label="Rows per page"
        >
          {PAGE_SIZES.map((size) => <option key={size} value={size}>{size} / page</option>)}
        </select>
        <div className="relative">
          <button
            type="button"
            onClick={() => setColumnMenuOpen((v) => !v)}
            className="flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            <SlidersHorizontal size={14} /> Columns
          </button>
          {columnMenuOpen && (
            <div className="absolute right-0 z-10 mt-1 w-56 rounded-lg border border-gray-200 bg-white p-2 shadow-lg">
              {columns.map((col) => (
                <label key={col.key} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50">
                  <input type="checkbox" checked={!hiddenColumns.has(col.key)} onChange={() => toggleColumn(col.key)} />
                  {col.header}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-[1] bg-gray-100">
            <tr>
              {visibleColumns.map((col) => (
                <th key={col.key} className={`px-4 py-2 font-medium text-gray-700 ${ALIGN_CLASS[col.align || 'left']}`}>{col.header}</th>
              ))}
              {actions && <th className="px-4 py-2 text-right font-medium text-gray-700">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row) => (
              <tr key={getRowId(row)} className="border-t border-gray-200 hover:bg-gray-50">
                {visibleColumns.map((col) => (
                  <td key={col.key} className={`px-4 py-2 ${ALIGN_CLASS[col.align || 'left']}`}>{col.render(row)}</td>
                ))}
                {actions && <td className="px-4 py-2 text-right whitespace-nowrap">{actions(row)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filteredRows.length === 0 && (
        <div className="py-8 text-center text-gray-500">{rows.length === 0 ? emptyMessage : 'No rows match your search.'}</div>
      )}

      {filteredRows.length > 0 && totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-sm text-gray-600">
          <span>
            {(currentPage - 1) * pageSize + 1}-{Math.min(currentPage * pageSize, filteredRows.length)} of {filteredRows.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}
              className="flex items-center gap-1 rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
            >
              <ChevronUp size={14} className="-rotate-90" /> Prev
            </button>
            <span className="px-2">{currentPage} / {totalPages}</span>
            <button
              type="button" disabled={currentPage >= totalPages} onClick={() => setPage(currentPage + 1)}
              className="flex items-center gap-1 rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
            >
              Next <ChevronDown size={14} className="-rotate-90" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
