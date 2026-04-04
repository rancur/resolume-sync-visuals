import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { Search, ChevronUp, ChevronDown, Sparkles, ChevronLeft, ChevronRight, AlertTriangle, ExternalLink, X } from 'lucide-react';
import { api, type Track, type BulkEstimate, type CreditStatus } from '../api/client';

const columnHelper = createColumnHelper<Track>();
const PAGE_SIZE = 50;

function StatusBadge({ hasVideo }: { hasVideo: Track['status'] }) {
  const styles = {
    generated: 'bg-green-900/40 text-green-400 border-green-700/50',
    generating: 'bg-yellow-900/40 text-yellow-400 border-yellow-700/50',
    pending: 'bg-gray-800 text-gray-400 border-gray-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs border ${styles[hasVideo]}`}>
      {hasVideo === 'generated' ? 'Generated' : hasVideo === 'generating' ? 'Generating' : 'Pending'}
    </span>
  );
}

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="w-full bg-gray-800 rounded-full h-2">
      <div
        className={`h-2 rounded-full ${color}`}
        style={{ width: `${Math.round(pct)}%` }}
      />
    </div>
  );
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function Library() {
  const navigate = useNavigate();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [genreFilter, setGenreFilter] = useState('');
  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [page, setPage] = useState(0);
  const [genres, setGenres] = useState<string[]>([]);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Load genres from API
  useEffect(() => {
    api.getGenres().then(setGenres).catch(() => setGenres([]));
  }, []);

  // Fetch tracks with server-side params
  const fetchTracks = useCallback(() => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
    if (debouncedSearch) params.search = debouncedSearch;
    if (genreFilter) params.genre = genreFilter;
    if (sorting.length > 0) {
      params.sort_by = sorting[0].id;
      if (sorting[0].desc) params.sort_desc = 'true';
    }
    api.getTracks(params)
      .then(({ tracks: t, total: tot }) => {
        setTracks(t);
        setTotal(tot);
      })
      .catch((err) => {
        setError('Failed to load tracks. Check Lexicon connection.');
        setTracks([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [page, debouncedSearch, sorting, genreFilter]);

  useEffect(() => {
    fetchTracks();
  }, [fetchTracks]);

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, genreFilter, sorting]);

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'select',
        header: ({ table }) => (
          <input
            type="checkbox"
            className="accent-[#4FC3F7]"
            checked={table.getIsAllRowsSelected()}
            onChange={table.getToggleAllRowsSelectedHandler()}
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            className="accent-[#4FC3F7]"
            checked={row.getIsSelected()}
            onChange={row.getToggleSelectedHandler()}
          />
        ),
        size: 40,
      }),
      columnHelper.accessor('title', {
        header: 'Title',
        cell: (info) => (
          <span className="text-white font-medium">{info.getValue()}</span>
        ),
      }),
      columnHelper.accessor('artist', { header: 'Artist' }),
      columnHelper.accessor('bpm', { header: 'BPM', size: 70 }),
      columnHelper.accessor('genre', { header: 'Genre' }),
      columnHelper.accessor('key', { header: 'Key', size: 60 }),
      columnHelper.accessor('energy', {
        header: 'Energy',
        cell: (info) => (
          <div className="flex items-center gap-2 min-w-[80px]">
            <ProgressBar value={info.getValue()} max={1} color="bg-orange-500" />
            <span className="text-xs text-gray-500 w-7">
              {Math.round(info.getValue() * 10)}
            </span>
          </div>
        ),
      }),
      columnHelper.accessor('happiness', {
        header: 'Mood',
        cell: (info) => (
          <div className="flex items-center gap-2 min-w-[80px]">
            <ProgressBar value={info.getValue()} max={1} color="bg-[#4FC3F7]" />
            <span className="text-xs text-gray-500 w-7">
              {Math.round(info.getValue() * 10)}
            </span>
          </div>
        ),
      }),
      columnHelper.accessor('duration', {
        header: 'Duration',
        cell: (info) => formatDuration(info.getValue()),
        size: 80,
      }),
      columnHelper.accessor('status', {
        header: 'Status',
        cell: (info) => <StatusBadge hasVideo={info.getValue()} />,
      }),
    ],
    []
  );

  const table = useReactTable({
    data: tracks,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableRowSelection: true,
    getRowId: (row) => row.id,
  });

  const selectedCount = Object.keys(rowSelection).length;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  // Cost confirmation modal state
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmEstimate, setConfirmEstimate] = useState<BulkEstimate | null>(null);
  const [confirmCredits, setConfirmCredits] = useState<CreditStatus | null>(null);
  const [confirmLoading, setConfirmLoading] = useState(false);

  const openConfirmModal = async () => {
    const ids = Object.keys(rowSelection);
    if (ids.length === 0) return;
    setShowConfirm(true);
    setConfirmLoading(true);
    try {
      const [est, cred] = await Promise.allSettled([
        api.getBulkEstimate(ids.length),
        api.checkCredits(),
      ]);
      setConfirmEstimate(est.status === 'fulfilled' ? est.value : null);
      setConfirmCredits(cred.status === 'fulfilled' ? cred.value : null);
    } catch {
      // proceed without estimate
    }
    setConfirmLoading(false);
  };

  const handleGenerate = async () => {
    const ids = Object.keys(rowSelection);
    if (ids.length === 0) return;
    setError(null);
    setShowConfirm(false);
    try {
      await api.createJob({ track_ids: ids });
      setRowSelection({});
    } catch (err) {
      setError(`Failed to start generation: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Track Library</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total.toLocaleString()} tracks</p>
        </div>
        {selectedCount > 0 && (
          <button
            onClick={openConfirmModal}
            className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
          >
            <Sparkles className="w-4 h-4" />
            Generate Selected ({selectedCount})
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="Search tracks..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-[#4FC3F7] transition-colors"
          />
        </div>
        <select
          value={genreFilter}
          onChange={(e) => setGenreFilter(e.target.value)}
          className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-[#4FC3F7]"
        >
          <option value="">All Genres</option>
          {genres.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="bg-gray-850 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
          </div>
        ) : tracks.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            {debouncedSearch || genreFilter
              ? 'No tracks match your search. Try different filters.'
              : 'No tracks found. Check Lexicon connection in Settings.'}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id} className="border-b border-gray-800">
                      {hg.headers.map((header) => (
                        <th
                          key={header.id}
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer select-none hover:text-gray-300"
                          onClick={header.column.getToggleSortingHandler()}
                          style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}
                        >
                          <div className="flex items-center gap-1">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {header.column.getIsSorted() === 'asc' && (
                              <ChevronUp className="w-3 h-3" />
                            )}
                            {header.column.getIsSorted() === 'desc' && (
                              <ChevronDown className="w-3 h-3" />
                            )}
                          </div>
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-b border-gray-800/50 hover:bg-gray-800/40 cursor-pointer transition-colors"
                      onClick={(e) => {
                        const tag = (e.target as HTMLElement).tagName;
                        if (tag === 'INPUT') return;
                        navigate(`/library/${row.original.id}`);
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-3">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-800">
                <span className="text-xs text-gray-500">
                  Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total.toLocaleString()}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage(p => p - 1)}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  {/* Show page numbers */}
                  {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                    let pageNum: number;
                    if (totalPages <= 7) {
                      pageNum = i;
                    } else if (page < 3) {
                      pageNum = i;
                    } else if (page > totalPages - 4) {
                      pageNum = totalPages - 7 + i;
                    } else {
                      pageNum = page - 3 + i;
                    }
                    return (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum)}
                        className={`w-8 h-8 rounded-lg text-xs transition-colors ${
                          page === pageNum
                            ? 'bg-[#4FC3F7]/15 text-[#4FC3F7] font-medium'
                            : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                        }`}
                      >
                        {pageNum + 1}
                      </button>
                    );
                  })}
                  <button
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage(p => p + 1)}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Cost Confirmation Modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-800 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Confirm Generation</h2>
              <button
                onClick={() => setShowConfirm(false)}
                className="p-1 text-gray-400 hover:text-gray-200 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Credit status warning */}
            {confirmCredits?.status === 'exhausted' && (
              <div className="flex items-center gap-3 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm">
                <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                <div>
                  <p className="font-medium">Credits exhausted</p>
                  <p className="text-xs mt-0.5 opacity-80">
                    Top up your fal.ai balance before generating.
                  </p>
                </div>
                <a
                  href="https://fal.ai/dashboard/billing"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-red-300 hover:text-red-200 underline flex-shrink-0"
                >
                  Top Up <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            )}

            {confirmLoading ? (
              <div className="flex items-center justify-center py-6">
                <div className="animate-spin w-6 h-6 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-900/50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Tracks</p>
                    <p className="text-xl font-semibold text-white">{selectedCount}</p>
                  </div>
                  <div className="bg-gray-900/50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Estimated Cost</p>
                    <p className="text-xl font-semibold text-white">
                      {confirmEstimate
                        ? `$${confirmEstimate.estimated_total.toFixed(2)}`
                        : '--'}
                    </p>
                  </div>
                </div>
                {confirmEstimate && (
                  <p className="text-xs text-gray-500">
                    Based on ${confirmEstimate.avg_cost_per_track.toFixed(4)} avg/track
                    {confirmEstimate.based_on_tracks > 0
                      ? ` from ${confirmEstimate.based_on_tracks} past generations`
                      : ' (default estimate)'}
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerate}
                disabled={confirmCredits?.status === 'exhausted'}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-[#4FC3F7] text-gray-900 rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Sparkles className="w-4 h-4" />
                {confirmCredits?.status === 'exhausted' ? 'Credits Exhausted' : 'Generate'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
