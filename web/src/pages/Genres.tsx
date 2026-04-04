import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import {
  ArrowLeft,
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  Music2,
} from 'lucide-react';
import { api, type GenreStats, type Track } from '../api/client';

// Genre family color mapping
const GENRE_FAMILIES: Record<string, { bg: string; border: string; text: string; bar: string }> = {
  bass: { bg: 'bg-red-900/30', border: 'border-red-700/40', text: 'text-red-400', bar: 'bg-red-500' },
  dubstep: { bg: 'bg-red-900/30', border: 'border-red-700/40', text: 'text-red-400', bar: 'bg-red-500' },
  drum: { bg: 'bg-red-900/30', border: 'border-red-700/40', text: 'text-red-400', bar: 'bg-red-500' },
  dnb: { bg: 'bg-red-900/30', border: 'border-red-700/40', text: 'text-red-400', bar: 'bg-red-500' },
  house: { bg: 'bg-blue-900/30', border: 'border-blue-700/40', text: 'text-blue-400', bar: 'bg-blue-500' },
  deep: { bg: 'bg-blue-900/30', border: 'border-blue-700/40', text: 'text-blue-400', bar: 'bg-blue-500' },
  tech: { bg: 'bg-indigo-900/30', border: 'border-indigo-700/40', text: 'text-indigo-400', bar: 'bg-indigo-500' },
  techno: { bg: 'bg-indigo-900/30', border: 'border-indigo-700/40', text: 'text-indigo-400', bar: 'bg-indigo-500' },
  trance: { bg: 'bg-purple-900/30', border: 'border-purple-700/40', text: 'text-purple-400', bar: 'bg-purple-500' },
  progressive: { bg: 'bg-purple-900/30', border: 'border-purple-700/40', text: 'text-purple-400', bar: 'bg-purple-500' },
  ambient: { bg: 'bg-cyan-900/30', border: 'border-cyan-700/40', text: 'text-cyan-400', bar: 'bg-cyan-500' },
  chill: { bg: 'bg-cyan-900/30', border: 'border-cyan-700/40', text: 'text-cyan-400', bar: 'bg-cyan-500' },
  downtempo: { bg: 'bg-cyan-900/30', border: 'border-cyan-700/40', text: 'text-cyan-400', bar: 'bg-cyan-500' },
  lofi: { bg: 'bg-cyan-900/30', border: 'border-cyan-700/40', text: 'text-cyan-400', bar: 'bg-cyan-500' },
  hip: { bg: 'bg-yellow-900/30', border: 'border-yellow-700/40', text: 'text-yellow-400', bar: 'bg-yellow-500' },
  rap: { bg: 'bg-yellow-900/30', border: 'border-yellow-700/40', text: 'text-yellow-400', bar: 'bg-yellow-500' },
  trap: { bg: 'bg-yellow-900/30', border: 'border-yellow-700/40', text: 'text-yellow-400', bar: 'bg-yellow-500' },
  pop: { bg: 'bg-pink-900/30', border: 'border-pink-700/40', text: 'text-pink-400', bar: 'bg-pink-500' },
  edm: { bg: 'bg-emerald-900/30', border: 'border-emerald-700/40', text: 'text-emerald-400', bar: 'bg-emerald-500' },
  electro: { bg: 'bg-emerald-900/30', border: 'border-emerald-700/40', text: 'text-emerald-400', bar: 'bg-emerald-500' },
  future: { bg: 'bg-violet-900/30', border: 'border-violet-700/40', text: 'text-violet-400', bar: 'bg-violet-500' },
  hardstyle: { bg: 'bg-orange-900/30', border: 'border-orange-700/40', text: 'text-orange-400', bar: 'bg-orange-500' },
  hard: { bg: 'bg-orange-900/30', border: 'border-orange-700/40', text: 'text-orange-400', bar: 'bg-orange-500' },
  garage: { bg: 'bg-lime-900/30', border: 'border-lime-700/40', text: 'text-lime-400', bar: 'bg-lime-500' },
  uk: { bg: 'bg-lime-900/30', border: 'border-lime-700/40', text: 'text-lime-400', bar: 'bg-lime-500' },
  breaks: { bg: 'bg-amber-900/30', border: 'border-amber-700/40', text: 'text-amber-400', bar: 'bg-amber-500' },
  breakbeat: { bg: 'bg-amber-900/30', border: 'border-amber-700/40', text: 'text-amber-400', bar: 'bg-amber-500' },
  jungle: { bg: 'bg-amber-900/30', border: 'border-amber-700/40', text: 'text-amber-400', bar: 'bg-amber-500' },
  disco: { bg: 'bg-fuchsia-900/30', border: 'border-fuchsia-700/40', text: 'text-fuchsia-400', bar: 'bg-fuchsia-500' },
  funk: { bg: 'bg-fuchsia-900/30', border: 'border-fuchsia-700/40', text: 'text-fuchsia-400', bar: 'bg-fuchsia-500' },
};

const DEFAULT_COLORS = { bg: 'bg-gray-800/40', border: 'border-gray-700/40', text: 'text-gray-400', bar: 'bg-gray-500' };

function getGenreColors(genre: string) {
  const lower = genre.toLowerCase();
  for (const [key, colors] of Object.entries(GENRE_FAMILIES)) {
    if (lower.includes(key)) return colors;
  }
  return DEFAULT_COLORS;
}

type SortKey = 'genre' | 'track_count' | 'visual_pct';

const PAGE_SIZE = 50;
const columnHelper = createColumnHelper<Track>();

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function StatusBadge({ status }: { status: Track['status'] }) {
  const styles = {
    generated: 'bg-green-900/40 text-green-400 border-green-700/50',
    generating: 'bg-yellow-900/40 text-yellow-400 border-yellow-700/50',
    pending: 'bg-gray-800 text-gray-400 border-gray-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs border ${styles[status]}`}>
      {status === 'generated' ? 'Generated' : status === 'generating' ? 'Generating' : 'Pending'}
    </span>
  );
}

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="w-full bg-gray-800 rounded-full h-2">
      <div className={`h-2 rounded-full ${color}`} style={{ width: `${Math.round(pct)}%` }} />
    </div>
  );
}

export default function Genres() {
  const navigate = useNavigate();
  const [genres, setGenres] = useState<GenreStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('track_count');
  const [sortDesc, setSortDesc] = useState(true);

  // Track detail view state
  const [selectedGenre, setSelectedGenre] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [tracksTotal, setTracksTotal] = useState(0);
  const [tracksLoading, setTracksLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([]);

  useEffect(() => {
    setLoading(true);
    api.getGenreStats()
      .then(setGenres)
      .catch(() => setError('Failed to load genre stats.'))
      .finally(() => setLoading(false));
  }, []);

  const sortedGenres = useMemo(() => {
    const sorted = [...genres];
    sorted.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDesc ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
      }
      return sortDesc ? (bVal as number) - (aVal as number) : (aVal as number) - (bVal as number);
    });
    return sorted;
  }, [genres, sortKey, sortDesc]);

  const fetchGenreTracks = useCallback(() => {
    if (!selectedGenre) return;
    setTracksLoading(true);
    const params: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
    if (sorting.length > 0) {
      params.sort_by = sorting[0].id;
      if (sorting[0].desc) params.sort_desc = 'true';
    }
    api.getGenreTracks(selectedGenre, params)
      .then(({ tracks: t, total }) => {
        setTracks(t);
        setTracksTotal(total);
      })
      .catch(() => setTracks([]))
      .finally(() => setTracksLoading(false));
  }, [selectedGenre, page, sorting]);

  useEffect(() => {
    fetchGenreTracks();
  }, [fetchGenreTracks]);

  useEffect(() => {
    setPage(0);
  }, [selectedGenre, sorting]);

  const columns = useMemo(
    () => [
      columnHelper.accessor('title', {
        header: 'Title',
        cell: (info) => <span className="text-white font-medium">{info.getValue()}</span>,
      }),
      columnHelper.accessor('artist', { header: 'Artist' }),
      columnHelper.accessor('bpm', { header: 'BPM', size: 70 }),
      columnHelper.accessor('key', { header: 'Key', size: 60 }),
      columnHelper.accessor('energy', {
        header: 'Energy',
        cell: (info) => (
          <div className="flex items-center gap-2 min-w-[80px]">
            <ProgressBar value={info.getValue()} max={1} color="bg-orange-500" />
            <span className="text-xs text-gray-500 w-7">{Math.round(info.getValue() * 10)}</span>
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
        cell: (info) => <StatusBadge status={info.getValue()} />,
      }),
    ],
    []
  );

  const table = useReactTable({
    data: tracks,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.id,
  });

  const totalPages = Math.ceil(tracksTotal / PAGE_SIZE);

  // Genre detail view
  if (selectedGenre) {
    const genreInfo = genres.find(g => g.genre === selectedGenre);
    const colors = getGenreColors(selectedGenre);
    return (
      <div className="p-6">
        <button
          onClick={() => setSelectedGenre(null)}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 mb-4 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Genres
        </button>

        <div className="flex items-center gap-4 mb-6">
          <div className={`p-3 rounded-xl ${colors.bg} border ${colors.border}`}>
            <Music2 className={`w-6 h-6 ${colors.text}`} />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-white">{selectedGenre}</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {genreInfo?.track_count ?? 0} tracks
              {genreInfo ? ` \u00b7 ${genreInfo.avg_bpm} avg BPM \u00b7 ${genreInfo.visual_pct}% with visuals` : ''}
            </p>
          </div>
        </div>

        <div className="bg-gray-850 border border-gray-800 rounded-xl overflow-hidden">
          {tracksLoading ? (
            <div className="flex items-center justify-center py-16">
              <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
            </div>
          ) : tracks.length === 0 ? (
            <div className="text-center py-12 text-gray-500">No tracks in this genre.</div>
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
                              {header.column.getIsSorted() === 'asc' && <ChevronUp className="w-3 h-3" />}
                              {header.column.getIsSorted() === 'desc' && <ChevronDown className="w-3 h-3" />}
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
                        onClick={() => navigate(`/library/${row.original.id}`)}
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

              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-800">
                  <span className="text-xs text-gray-500">
                    Showing {page * PAGE_SIZE + 1}--{Math.min((page + 1) * PAGE_SIZE, tracksTotal)} of {tracksTotal.toLocaleString()}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      disabled={page === 0}
                      onClick={() => setPage(p => p - 1)}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                      let pageNum: number;
                      if (totalPages <= 7) pageNum = i;
                      else if (page < 3) pageNum = i;
                      else if (page > totalPages - 4) pageNum = totalPages - 7 + i;
                      else pageNum = page - 3 + i;
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
      </div>
    );
  }

  // Genre grid view
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(key);
      setSortDesc(key !== 'genre');
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Genres</h1>
          <p className="text-sm text-gray-500 mt-0.5">{genres.length} genres across your library</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 mr-1">Sort:</span>
          {([
            ['genre', 'Name'],
            ['track_count', 'Tracks'],
            ['visual_pct', 'Completion'],
          ] as [SortKey, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => handleSort(key)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                sortKey === key
                  ? 'bg-[#4FC3F7]/15 text-[#4FC3F7] font-medium'
                  : 'text-gray-400 hover:text-gray-200 bg-gray-800/60 hover:bg-gray-800'
              }`}
            >
              {label}
              {sortKey === key && (sortDesc ? ' \u2193' : ' \u2191')}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {sortedGenres.map((g) => {
            const colors = getGenreColors(g.genre);
            return (
              <button
                key={g.genre}
                onClick={() => setSelectedGenre(g.genre)}
                className={`${colors.bg} border ${colors.border} rounded-xl p-4 text-left hover:scale-[1.02] transition-all duration-150 group`}
              >
                <div className="flex items-start justify-between mb-3">
                  <h3 className={`font-semibold text-sm ${colors.text} group-hover:text-white transition-colors truncate mr-2`}>
                    {g.genre}
                  </h3>
                  <span className="text-xs text-gray-500 whitespace-nowrap">{g.track_count} tracks</span>
                </div>

                {/* Visual completion bar */}
                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-500">Visuals</span>
                    <span className={`text-xs font-medium ${g.visual_pct > 0 ? colors.text : 'text-gray-600'}`}>
                      {g.visual_pct}%
                    </span>
                  </div>
                  <div className="w-full bg-gray-800/60 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full ${colors.bar} transition-all`}
                      style={{ width: `${g.visual_pct}%` }}
                    />
                  </div>
                </div>

                {/* Stats row */}
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <div className="flex items-center gap-1">
                    <BarChart3 className="w-3 h-3" />
                    <span>{g.avg_bpm} BPM</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span>Energy {g.avg_energy}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
