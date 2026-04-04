import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Music,
  Video,
  History,
  LayoutGrid,
  RefreshCw,
  Play,
  Wand2,
  Save,
  Trash2,
  CheckCircle,
  XCircle,
  Loader2,
  DollarSign,
  Clock as ClockIcon,
  ExternalLink,
  AlertTriangle,
  BarChart3,
} from 'lucide-react';
import {
  api,
  type Track,
  type TrackPrompt,
  type ColorEntry,
  type TrackHistory,
  type TrackHistoryJob,
  type TrackMetadata,
} from '../api/client';

type TabId = 'overview' | 'prompt' | 'keyframes' | 'video' | 'history' | 'metadata';

function StatusBadge({ status }: { status: Track['status'] }) {
  const styles = {
    generated: 'bg-green-900/40 text-green-400 border-green-700/50',
    generating: 'bg-yellow-900/40 text-yellow-400 border-yellow-700/50',
    pending: 'bg-gray-800 text-gray-400 border-gray-700',
  };
  return (
    <span className={`px-2.5 py-1 rounded-full text-xs border ${styles[status]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function TrackDetail() {
  const { trackId } = useParams<{ trackId: string }>();
  const navigate = useNavigate();
  const [track, setTrack] = useState<Track | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [showRegenModal, setShowRegenModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<TrackPrompt>({ track_id: '', global_prompt: '', section_prompts: {} });
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptSaved, setPromptSaved] = useState(false);
  const [palette, setPalette] = useState<ColorEntry[]>([]);
  const [paletteLoading, setPaletteLoading] = useState(false);
  const [history, setHistory] = useState<TrackHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [metadata, setMetadata] = useState<TrackMetadata | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);

  useEffect(() => {
    if (!trackId) return;
    Promise.all([
      api.getTrack(trackId).then(setTrack),
      api.getTrackPrompt(trackId).then(setPrompt).catch(() => {}),
    ])
      .catch(() => {
        setError('Failed to load track. It may not exist or Lexicon may be unavailable.');
      })
      .finally(() => setLoading(false));

    // Load palette separately (may be slow)
    setPaletteLoading(true);
    api.getTrackColors(trackId)
      .then((r) => setPalette(r.palette || []))
      .catch(() => setPalette([]))
      .finally(() => setPaletteLoading(false));

    // Load generation history
    setHistoryLoading(true);
    api.getTrackHistory(trackId)
      .then(setHistory)
      .catch(() => setHistory(null))
      .finally(() => setHistoryLoading(false));

    // Load rich metadata
    setMetadataLoading(true);
    api.getTrackMetadata(trackId)
      .then(setMetadata)
      .catch(() => setMetadata(null))
      .finally(() => setMetadataLoading(false));
  }, [trackId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!track) {
    return (
      <div className="p-6">
        <button
          onClick={() => navigate('/library')}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 mb-4 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Library
        </button>
        {error && (
          <div className="mb-4 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm">
            {error}
          </div>
        )}
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Music className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">Track not found</p>
        </div>
      </div>
    );
  }

  const tabs: { id: TabId; label: string; icon: React.ElementType }[] = [
    { id: 'overview', label: 'Overview', icon: LayoutGrid },
    { id: 'prompt', label: 'Custom Prompt', icon: Wand2 },
    { id: 'keyframes', label: 'Keyframes', icon: Music },
    { id: 'video', label: 'Video Player', icon: Video },
    { id: 'history', label: 'Generation History', icon: History },
    { id: 'metadata', label: 'Rich Metadata', icon: BarChart3 },
  ];

  const SECTIONS = ['intro', 'build', 'drop', 'breakdown', 'outro'];

  const handleSavePrompt = async () => {
    if (!trackId) return;
    setPromptSaving(true);
    try {
      const result = await api.setTrackPrompt(trackId, {
        global_prompt: prompt.global_prompt,
        section_prompts: prompt.section_prompts,
      });
      setPrompt(result);
      setPromptSaved(true);
      setTimeout(() => setPromptSaved(false), 2000);
    } catch (err) {
      setError(`Failed to save prompt: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    setPromptSaving(false);
  };

  const handleClearPrompt = async () => {
    if (!trackId) return;
    try {
      await api.clearTrackPrompt(trackId);
      setPrompt({ track_id: trackId, global_prompt: '', section_prompts: {} });
    } catch (err) {
      setError(`Failed to clear prompt: ${err instanceof Error ? err.message : 'Unknown error'}`);
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
      {/* Back button + header */}
      <button
        onClick={() => navigate('/library')}
        className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Library
      </button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">{track.title}</h1>
          <p className="text-gray-400">{track.artist}</p>
          <div className="flex items-center gap-3 mt-2">
            <StatusBadge status={track.status} />
            <span className="text-xs text-gray-500">{track.bpm} BPM</span>
            <span className="text-xs text-gray-500">{track.key}</span>
            <span className="text-xs text-gray-500">{track.genre}</span>
            <span className="text-xs text-gray-500">{formatDuration(track.duration)}</span>
          </div>
        </div>
        <button
          onClick={() => setShowRegenModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Regenerate
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-800 mb-6">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm border-b-2 transition-colors ${
              activeTab === id
                ? 'border-[#4FC3F7] text-[#4FC3F7]'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              Audio Features
            </h3>
            {[
              { label: 'Energy', value: track.energy, color: 'bg-orange-500' },
              { label: 'Mood', value: track.happiness, color: 'bg-[#4FC3F7]' },
            ].map((f) => (
              <div key={f.label}>
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                  <span>{f.label}</span>
                  <span>{Math.round(f.value * 10)} / 10</span>
                </div>
                <div className="w-full bg-gray-900 rounded-full h-2.5">
                  <div
                    className={`h-2.5 rounded-full ${f.color}`}
                    style={{ width: `${f.value * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              Metadata
            </h3>
            {[
              { label: 'BPM', value: track.bpm },
              { label: 'Key', value: track.key },
              { label: 'Genre', value: track.genre },
              { label: 'Duration', value: formatDuration(track.duration) },
              { label: 'Created', value: track.created_at },
            ].map((m) => (
              <div key={m.label} className="flex justify-between text-sm">
                <span className="text-gray-500">{m.label}</span>
                <span className="text-gray-200">{m.value}</span>
              </div>
            ))}
          </div>

          {/* Color Palette */}
          <div className="md:col-span-2 bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              Album Art Color Palette
            </h3>
            {paletteLoading ? (
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <div className="animate-spin w-4 h-4 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
                Extracting colors...
              </div>
            ) : palette.length === 0 ? (
              <p className="text-xs text-gray-600">No album art found in this track's audio file.</p>
            ) : (
              <div className="space-y-3">
                <div className="flex gap-3 flex-wrap">
                  {palette.map((c, i) => (
                    <div key={i} className="text-center">
                      <div
                        className="w-14 h-14 rounded-lg border border-gray-700 shadow-lg"
                        style={{ backgroundColor: c.hex }}
                      />
                      <p className="text-xs text-gray-400 mt-1 capitalize">{c.name}</p>
                      <p className="text-[10px] text-gray-600 font-mono">{c.hex}</p>
                      <p className="text-[10px] text-gray-600">{Math.round(c.weight * 100)}%</p>
                    </div>
                  ))}
                </div>
                <div
                  className="h-6 rounded-lg overflow-hidden flex"
                  title="Color gradient from album art"
                >
                  {palette.map((c, i) => (
                    <div
                      key={i}
                      className="h-full"
                      style={{ backgroundColor: c.hex, width: `${c.weight * 100}%` }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'prompt' && (
        <div className="space-y-6">
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                Global Prompt Override
              </h3>
              <div className="flex items-center gap-2">
                {(prompt.global_prompt || Object.values(prompt.section_prompts).some(v => v)) && (
                  <button
                    onClick={handleClearPrompt}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-3 h-3" />
                    Clear All
                  </button>
                )}
                <button
                  onClick={handleSavePrompt}
                  disabled={promptSaving}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
                >
                  <Save className="w-3 h-3" />
                  {promptSaved ? 'Saved!' : promptSaving ? 'Saving...' : 'Save Prompt'}
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500">
              This prompt is injected alongside the brand guide and mood-derived prompts during generation. It does not replace them.
            </p>
            <textarea
              value={prompt.global_prompt}
              onChange={(e) => setPrompt(p => ({ ...p, global_prompt: e.target.value }))}
              placeholder="e.g., giant robot fighting a dragon, cyberpunk tokyo neon rain..."
              rows={3}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7] resize-y"
            />
          </div>

          <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              Per-Section Prompts
            </h3>
            <p className="text-xs text-gray-500">
              Override prompts for specific song sections. Leave blank to use the global prompt + brand defaults.
            </p>
            <div className="space-y-3">
              {SECTIONS.map((section) => (
                <div key={section}>
                  <label className="text-xs text-gray-400 uppercase tracking-wider mb-1 block">
                    {section}
                  </label>
                  <input
                    type="text"
                    value={prompt.section_prompts[section] || ''}
                    onChange={(e) =>
                      setPrompt(p => ({
                        ...p,
                        section_prompts: { ...p.section_prompts, [section]: e.target.value },
                      }))
                    }
                    placeholder={`Custom prompt for ${section} section...`}
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'keyframes' && (
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Keyframe Timeline
          </h3>
          <div className="space-y-2">
            {['0:00 - Intro', '0:32 - Build', '1:04 - Drop', '1:36 - Breakdown', '2:08 - Build 2', '2:40 - Drop 2', '3:12 - Outro'].map(
              (kf, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg"
                >
                  <div className="w-2 h-2 rounded-full bg-[#4FC3F7]" />
                  <span className="text-sm text-gray-300">{kf}</span>
                </div>
              )
            )}
          </div>
        </div>
      )}

      {activeTab === 'video' && (
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          {track.video_url ? (
            <video
              src={track.video_url}
              controls
              className="w-full rounded-lg bg-black"
            >
              Your browser does not support video playback.
            </video>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-gray-500">
              <Play className="w-12 h-12 mb-3 opacity-30" />
              <p>No video generated yet</p>
              <p className="text-xs mt-1">
                Generate visuals to preview the video here
              </p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'history' && (
        <div className="space-y-6">
          {/* Summary */}
          {history && history.total_jobs > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <ClockIcon className="w-4 h-4 text-[#4FC3F7]" />
                  <span className="text-xs text-gray-500">Total Runs</span>
                </div>
                <p className="text-xl font-semibold text-white">{history.total_jobs}</p>
              </div>
              <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <DollarSign className="w-4 h-4 text-[#4FC3F7]" />
                  <span className="text-xs text-gray-500">Total Cost</span>
                </div>
                <p className="text-xl font-semibold text-white">${history.total_cost.toFixed(2)}</p>
              </div>
              <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle className="w-4 h-4 text-green-400" />
                  <span className="text-xs text-gray-500">Success Rate</span>
                </div>
                <p className="text-xl font-semibold text-white">
                  {history.total_jobs > 0
                    ? `${Math.round(
                        (history.jobs.filter((j) => j.status === 'completed').length /
                          history.total_jobs) *
                          100
                      )}%`
                    : 'N/A'}
                </p>
              </div>
            </div>
          )}

          {/* Generation Runs */}
          <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                Generation Runs
              </h3>
              <button
                onClick={() => setShowRegenModal(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
              >
                <RefreshCw className="w-3 h-3" />
                Regenerate
              </button>
            </div>

            {historyLoading ? (
              <div className="flex items-center gap-2 text-xs text-gray-500 py-8 justify-center">
                <div className="animate-spin w-4 h-4 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
                Loading history...
              </div>
            ) : !history || history.jobs.length === 0 ? (
              <div className="text-sm text-gray-500 py-8 text-center">
                No generation history available for this track.
              </div>
            ) : (
              <div className="space-y-3">
                {history.jobs.map((job: TrackHistoryJob) => (
                  <div
                    key={job.id}
                    className="flex items-start gap-3 p-3 bg-gray-900/40 rounded-lg"
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      {job.status === 'completed' && (
                        <CheckCircle className="w-4 h-4 text-green-400" />
                      )}
                      {job.status === 'failed' && (
                        <XCircle className="w-4 h-4 text-red-400" />
                      )}
                      {job.status === 'running' && (
                        <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                      )}
                      {!['completed', 'failed', 'running'].includes(job.status) && (
                        <AlertTriangle className="w-4 h-4 text-gray-500" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full border ${
                            job.status === 'completed'
                              ? 'bg-green-900/30 text-green-400 border-green-700/50'
                              : job.status === 'failed'
                              ? 'bg-red-900/30 text-red-400 border-red-700/50'
                              : job.status === 'running'
                              ? 'bg-blue-900/30 text-blue-400 border-blue-700/50'
                              : 'bg-gray-800 text-gray-400 border-gray-700'
                          }`}
                        >
                          {job.status}
                        </span>
                        {job.model && (
                          <span className="text-xs text-gray-500">Model: {job.model}</span>
                        )}
                        {job.quality && (
                          <span className="text-xs text-gray-500">Quality: {job.quality}</span>
                        )}
                        {job.segments > 0 && (
                          <span className="text-xs text-gray-500">
                            {job.segments} segments
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                        <span>{job.created_at}</span>
                        {job.cost > 0 && <span>${job.cost.toFixed(4)}</span>}
                        {job.duration_secs != null && (
                          <span>
                            {job.duration_secs > 60
                              ? `${Math.floor(job.duration_secs / 60)}m ${Math.round(
                                  job.duration_secs % 60
                                )}s`
                              : `${Math.round(job.duration_secs)}s`}
                          </span>
                        )}
                      </div>
                      {job.error && (
                        <p className="text-xs text-red-400 mt-1 truncate">{job.error}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {job.has_video && (
                        <button
                          onClick={() => setActiveTab('video')}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-[#4FC3F7] hover:text-[#81D4FA] bg-[rgba(79,195,247,0.1)] rounded transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          View Video
                        </button>
                      )}
                      {job.status === 'failed' && (
                        <button
                          onClick={async () => {
                            try {
                              await api.retryJob(job.id);
                              // Refresh history
                              if (trackId) {
                                const h = await api.getTrackHistory(trackId);
                                setHistory(h);
                              }
                            } catch (err) {
                              setError(
                                `Retry failed: ${
                                  err instanceof Error ? err.message : 'Unknown error'
                                }`
                              );
                            }
                          }}
                          className="flex items-center gap-1 px-2 py-1 text-xs text-yellow-400 hover:text-yellow-300 bg-yellow-900/20 rounded transition-colors"
                        >
                          <RefreshCw className="w-3 h-3" />
                          Retry
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Per-API-Call Cost Details */}
          {history && history.cost_details.length > 0 && (
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
              <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
                API Call Details
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-700/50">
                      <th className="text-left py-2 pr-4">Time</th>
                      <th className="text-left py-2 pr-4">Model</th>
                      <th className="text-left py-2 pr-4">Section</th>
                      <th className="text-right py-2 pr-4">Cost</th>
                      <th className="text-left py-2">Cached</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.cost_details.slice(0, 50).map((c, i) => (
                      <tr key={i} className="border-b border-gray-800/50 text-gray-400">
                        <td className="py-1.5 pr-4 whitespace-nowrap">
                          {c.timestamp.split('T')[1]?.split('.')[0] || c.timestamp}
                        </td>
                        <td className="py-1.5 pr-4">{c.model}</td>
                        <td className="py-1.5 pr-4">{c.phrase_label || '-'}</td>
                        <td className="py-1.5 pr-4 text-right">
                          {c.cached ? (
                            <span className="text-green-400">cached</span>
                          ) : (
                            `$${c.cost_usd.toFixed(4)}`
                          )}
                        </td>
                        <td className="py-1.5">
                          {c.cached ? (
                            <span className="text-green-400">Yes</span>
                          ) : (
                            <span className="text-gray-600">No</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'metadata' && (
        <div className="space-y-6">
          {metadataLoading ? (
            <div className="flex items-center gap-2 text-xs text-gray-500 py-8 justify-center">
              <div className="animate-spin w-4 h-4 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
              Loading metadata...
            </div>
          ) : !metadata ? (
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 text-center text-gray-500">
              <BarChart3 className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm">No rich metadata available yet.</p>
              <p className="text-xs mt-1 text-gray-600">Generate visuals to produce metadata.</p>
            </div>
          ) : (
            <>
              {/* Phrase Timeline */}
              {metadata.phrase_timeline.length > 0 && (
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                    Phrase Timeline
                  </h3>
                  <div className="flex h-10 rounded-lg overflow-hidden gap-0.5">
                    {metadata.phrase_timeline.map((phrase, i) => {
                      const totalDuration = metadata.track.duration || 1;
                      const widthPct = (phrase.duration / totalDuration) * 100;
                      const colors: Record<string, string> = {
                        intro: 'bg-blue-600',
                        buildup: 'bg-yellow-500',
                        build: 'bg-yellow-500',
                        drop: 'bg-red-500',
                        breakdown: 'bg-purple-500',
                        outro: 'bg-blue-400',
                      };
                      return (
                        <div
                          key={i}
                          className={`${colors[phrase.label] || 'bg-gray-600'} flex items-center justify-center text-[10px] text-white font-medium`}
                          style={{ width: `${widthPct}%`, minWidth: widthPct > 3 ? undefined : '2px' }}
                          title={`${phrase.label}: ${formatDuration(phrase.start)} - ${formatDuration(phrase.end)} (energy: ${(phrase.energy * 100).toFixed(0)}%)`}
                        >
                          {widthPct > 8 ? phrase.label : ''}
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex gap-3 flex-wrap text-[10px] text-gray-500">
                    {[
                      { label: 'intro', color: 'bg-blue-600' },
                      { label: 'buildup', color: 'bg-yellow-500' },
                      { label: 'drop', color: 'bg-red-500' },
                      { label: 'breakdown', color: 'bg-purple-500' },
                      { label: 'outro', color: 'bg-blue-400' },
                    ].map((l) => (
                      <div key={l.label} className="flex items-center gap-1">
                        <div className={`w-2.5 h-2.5 rounded-sm ${l.color}`} />
                        {l.label}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Energy Curve */}
              {metadata.energy_curve.length > 0 && (
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                    Energy Curve
                  </h3>
                  <div className="relative h-24">
                    <svg viewBox="0 0 400 100" className="w-full h-full" preserveAspectRatio="none">
                      <defs>
                        <linearGradient id="energyGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#4FC3F7" stopOpacity="0.6" />
                          <stop offset="100%" stopColor="#4FC3F7" stopOpacity="0.05" />
                        </linearGradient>
                      </defs>
                      {(() => {
                        const maxTime = metadata.track.duration || metadata.energy_curve[metadata.energy_curve.length - 1]?.time || 1;
                        const points = metadata.energy_curve.map(
                          (p) => `${(p.time / maxTime) * 400},${100 - p.energy * 100}`
                        );
                        const linePoints = points.join(' ');
                        const areaPoints = `0,100 ${linePoints} 400,100`;
                        return (
                          <>
                            <polygon points={areaPoints} fill="url(#energyGrad)" />
                            <polyline
                              points={linePoints}
                              fill="none"
                              stroke="#4FC3F7"
                              strokeWidth="2"
                            />
                          </>
                        );
                      })()}
                    </svg>
                    <div className="absolute bottom-0 left-0 text-[10px] text-gray-600">0:00</div>
                    <div className="absolute bottom-0 right-0 text-[10px] text-gray-600">
                      {formatDuration(metadata.track.duration)}
                    </div>
                  </div>
                </div>
              )}

              {/* Mood + Cost side by side */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Mood Analysis */}
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-3">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                    Mood Analysis
                  </h3>
                  {[
                    { label: 'Valence', value: metadata.mood.valence, color: 'bg-green-500' },
                    { label: 'Arousal', value: metadata.mood.arousal, color: 'bg-orange-500' },
                  ].map((m) => (
                    <div key={m.label}>
                      <div className="flex justify-between text-xs text-gray-400 mb-1">
                        <span>{m.label}</span>
                        <span>{(m.value * 100).toFixed(0)}%</span>
                      </div>
                      <div className="w-full bg-gray-900 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${m.color}`}
                          style={{ width: `${m.value * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  <div className="flex justify-between text-sm mt-2">
                    <span className="text-gray-500">Quadrant</span>
                    <span className="text-gray-200 capitalize">
                      {metadata.mood.quadrant.replace(/_/g, ' ')}
                    </span>
                  </div>
                  {metadata.mood.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {metadata.mood.tags.map((tag) => (
                        <span
                          key={tag}
                          className="px-2 py-0.5 bg-gray-900 text-gray-400 text-xs rounded-full border border-gray-700"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Cost Breakdown */}
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-3">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                    Cost Breakdown
                  </h3>
                  {[
                    { label: 'Total Cost', value: `$${metadata.cost_breakdown.total.toFixed(2)}` },
                    { label: 'Keyframes', value: `$${metadata.cost_breakdown.keyframes.toFixed(2)}` },
                    { label: 'Video', value: `$${metadata.cost_breakdown.video.toFixed(2)}` },
                    { label: 'Model', value: metadata.cost_breakdown.model || 'N/A' },
                    { label: 'Quality', value: metadata.cost_breakdown.quality || 'N/A' },
                  ].map((item) => (
                    <div key={item.label} className="flex justify-between text-sm">
                      <span className="text-gray-500">{item.label}</span>
                      <span className="text-gray-200">{item.value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Per-Segment Details */}
              {metadata.segments.length > 0 && (
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
                    Segment Details
                  </h3>
                  <div className="space-y-2">
                    {metadata.segments.map((seg) => (
                      <div
                        key={seg.index}
                        className="flex items-start gap-3 p-3 bg-gray-900/40 rounded-lg"
                      >
                        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center text-xs text-gray-400 font-mono">
                          {seg.index}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-medium text-gray-300 capitalize">
                              {seg.label}
                            </span>
                            <span className="text-[10px] text-gray-600">
                              {formatDuration(seg.start)} - {formatDuration(seg.end)}
                            </span>
                            {seg.cached && (
                              <span className="text-[10px] text-green-400">cached</span>
                            )}
                            {seg.cost > 0 && (
                              <span className="text-[10px] text-gray-500">
                                ${seg.cost.toFixed(4)}
                              </span>
                            )}
                          </div>
                          {seg.prompt && (
                            <p className="text-xs text-gray-500 truncate">{seg.prompt}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Stem Analysis */}
              {metadata.stems.available && (
                <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-3">
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
                    Stem Analysis
                  </h3>
                  {['drums', 'bass', 'vocals', 'other'].map((stem) => {
                    const data = (metadata.stems as any)[stem];
                    if (!data || typeof data !== 'object') return null;
                    const energy = data.energy ?? data.presence ?? 0;
                    const colors: Record<string, string> = {
                      drums: 'bg-red-500',
                      bass: 'bg-purple-500',
                      vocals: 'bg-[#4FC3F7]',
                      other: 'bg-green-500',
                    };
                    return (
                      <div key={stem}>
                        <div className="flex justify-between text-xs text-gray-400 mb-1">
                          <span className="capitalize">{stem}</span>
                          <span>{(energy * 100).toFixed(0)}%</span>
                        </div>
                        <div className="w-full bg-gray-900 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full ${colors[stem] || 'bg-gray-500'}`}
                            style={{ width: `${energy * 100}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Regenerate Modal */}
      {showRegenModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold text-white">Regenerate Visuals</h2>
            <p className="text-sm text-gray-400">
              This will create a new generation job for "{track.title}".
            </p>
            <div className="space-y-2">
              <label className="text-xs text-gray-500">Model Override (optional)</label>
              <select className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]">
                <option value="">Use default model</option>
                <option value="wan21">Wan-2.1</option>
                <option value="ltx">LTX-Video</option>
                <option value="runway3">Runway Gen-3</option>
              </select>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowRegenModal(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.createJob({ track_ids: [track.id] });
                    setShowRegenModal(false);
                  } catch (err) {
                    setError(`Failed to start regeneration: ${err instanceof Error ? err.message : 'Unknown error'}`);
                    setShowRegenModal(false);
                  }
                }}
                className="px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors text-sm"
              >
                Start Generation
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
