import { useState, useEffect, useRef } from 'react';
import { Search, ScrollText, AlertTriangle, Info, Bug, XCircle } from 'lucide-react';
import { api, type LogRun, type LogEntry } from '../api/client';

const levelColors: Record<string, string> = {
  debug: 'text-gray-500',
  info: 'text-[#4FC3F7]',
  warning: 'text-yellow-400',
  error: 'text-red-400',
};

const levelIcons: Record<string, React.ElementType> = {
  debug: Bug,
  info: Info,
  warning: AlertTriangle,
  error: XCircle,
};

export default function Logs() {
  const [runs, setRuns] = useState<LogRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [levelFilter, setLevelFilter] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getLogRuns()
      .then((r) => {
        setRuns(r);
        if (r.length > 0) setSelectedRun(r[0].id);
      })
      .catch(() => {
        setRuns([]);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedRun) return;
    const params: Record<string, string> = {};
    if (levelFilter) params.level = levelFilter;
    if (search) params.search = search;

    api.getLogRun(selectedRun)
      .then((r) => setEntries(r.events || []))
      .catch(() => setEntries([]));
  }, [selectedRun, levelFilter, search]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries]);

  const filteredEntries = entries.filter((e) => {
    if (levelFilter && e.level !== levelFilter) return false;
    if (search && !e.message.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-semibold text-white mb-8">Logs</h1>
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <ScrollText className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">No runs yet</p>
          <p className="text-sm mt-1">Generation run logs will appear here after processing tracks.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Run List */}
      <div className="w-72 flex-shrink-0 border-r border-gray-800 flex flex-col bg-gray-900/50">
        <div className="p-4 border-b border-gray-800">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider flex items-center gap-2">
            <ScrollText className="w-4 h-4" />
            Runs
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto">
          {runs.map((run) => (
            <button
              key={run.id}
              onClick={() => setSelectedRun(run.id)}
              className={`w-full text-left px-4 py-3 border-b border-gray-800/50 transition-colors ${
                selectedRun === run.id
                  ? 'bg-gray-800/80 border-l-2 border-l-[#4FC3F7]'
                  : 'hover:bg-gray-800/40'
              }`}
            >
              <p className="text-sm text-white truncate">{run.name}</p>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className={`text-xs ${
                    run.status === 'running'
                      ? 'text-green-400'
                      : run.status === 'failed'
                      ? 'text-red-400'
                      : 'text-gray-500'
                  }`}
                >
                  {run.status}
                </span>
                <span className="text-xs text-gray-600">{run.entry_count} entries</span>
              </div>
              <p className="text-[10px] text-gray-600 mt-0.5">
                {new Date(run.started_at).toLocaleString()}
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Log Entries */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Filters */}
        <div className="flex items-center gap-3 p-4 border-b border-gray-800">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              placeholder="Search logs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-[#4FC3F7]"
          >
            <option value="">All Levels</option>
            <option value="debug">Debug</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </div>

        {/* Entries */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto font-mono text-xs">
          {filteredEntries.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-600">
              {selectedRun ? 'No log entries match your filters' : 'Select a run to view logs'}
            </div>
          ) : (
            <div className="divide-y divide-gray-800/30">
              {filteredEntries.map((entry, i) => {
                const Icon = levelIcons[entry.level] || Info;
                return (
                  <div
                    key={i}
                    className="flex items-start gap-3 px-4 py-2 hover:bg-gray-800/30 transition-colors"
                  >
                    <Icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${levelColors[entry.level]}`} />
                    <span className="text-gray-600 flex-shrink-0 w-20">
                      {new Date(entry.timestamp).toLocaleTimeString()}
                    </span>
                    <span className="text-gray-500 flex-shrink-0 w-24 truncate">
                      {entry.module}
                    </span>
                    <span className={`flex-1 break-all ${entry.level === 'error' ? 'text-red-300' : 'text-gray-300'}`}>
                      {entry.message}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const demoRuns: LogRun[] = [
  { id: 'run1', name: 'Generate: Midnight Run', started_at: '2026-03-27T09:00:00Z', status: 'completed', entry_count: 47 },
  { id: 'run2', name: 'Generate: Neon Dreams', started_at: '2026-03-27T10:00:00Z', status: 'running', entry_count: 23 },
  { id: 'run3', name: 'Batch: Main Set', started_at: '2026-03-26T14:00:00Z', status: 'failed', entry_count: 89 },
];

const demoEntries: LogEntry[] = [
  { timestamp: '2026-03-27T09:00:01Z', level: 'info', message: 'Starting visual generation pipeline', module: 'pipeline' },
  { timestamp: '2026-03-27T09:00:02Z', level: 'info', message: 'Analyzing audio features...', module: 'analysis' },
  { timestamp: '2026-03-27T09:00:05Z', level: 'debug', message: 'BPM: 128, Key: Am, Energy: 0.85', module: 'analysis' },
  { timestamp: '2026-03-27T09:00:06Z', level: 'info', message: 'Generating keyframes for 7 sections', module: 'keyframe' },
  { timestamp: '2026-03-27T09:00:15Z', level: 'info', message: 'Keyframe 1/7 generated (intro)', module: 'keyframe' },
  { timestamp: '2026-03-27T09:00:25Z', level: 'info', message: 'Keyframe 2/7 generated (build)', module: 'keyframe' },
  { timestamp: '2026-03-27T09:00:35Z', level: 'warning', message: 'High VRAM usage (7.2GB/8GB), reducing batch size', module: 'gpu' },
  { timestamp: '2026-03-27T09:00:45Z', level: 'info', message: 'Keyframe 3/7 generated (drop)', module: 'keyframe' },
  { timestamp: '2026-03-27T09:01:00Z', level: 'info', message: 'Interpolating between keyframes...', module: 'interpolate' },
  { timestamp: '2026-03-27T09:02:30Z', level: 'info', message: 'Encoding final video (H.264, 1280x720)', module: 'encoder' },
  { timestamp: '2026-03-27T09:03:00Z', level: 'info', message: 'Uploading to NAS: /media/visuals/midnight-run.mp4', module: 'storage' },
  { timestamp: '2026-03-27T09:03:05Z', level: 'info', message: 'Generation complete. Cost: $0.0412, Duration: 3m05s', module: 'pipeline' },
];
