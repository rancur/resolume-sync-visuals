import { useState, useEffect } from 'react';
import {
  ListMusic,
  Plus,
  Trash2,
  ArrowRight,
  X,
  Hammer,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

interface SetlistTrack {
  id: string;
  title: string;
  artist: string;
  bpm?: number;
  duration?: number;
}

interface Setlist {
  id: string;
  name: string;
  description: string;
  tracks: SetlistTrack[];
  transitions: Record<string, { type: string; from_track: string; to_track: string }>;
  created_at: string;
  updated_at: string;
}

const TRANSITION_TYPES = ['crossfade', 'hard_cut', 'color_wash', 'zoom_through', 'fade_black'];

const TRANSITION_LABELS: Record<string, string> = {
  crossfade: 'Crossfade',
  hard_cut: 'Hard Cut',
  color_wash: 'Color Wash',
  zoom_through: 'Zoom Through',
  fade_black: 'Fade to Black',
};

export default function Setlists() {
  const [setlists, setSetlists] = useState<Setlist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [activeSetlist, setActiveSetlist] = useState<Setlist | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState('');

  const [newTrackTitle, setNewTrackTitle] = useState('');
  const [newTrackArtist, setNewTrackArtist] = useState('');

  const loadSetlists = async () => {
    try {
      const res = await fetch('/api/setlists');
      const data = await res.json();
      setSetlists(data.setlists || []);
    } catch {
      setError('Failed to load setlists');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadSetlists(); }, []);

  const handleCreate = async (name: string, desc: string) => {
    try {
      const res = await fetch('/api/setlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: desc }),
      });
      if (!res.ok) throw new Error('Create failed');
      setShowCreate(false);
      await loadSetlists();
    } catch {
      setError('Failed to create setlist');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this setlist?')) return;
    try {
      await fetch(`/api/setlists/${id}`, { method: 'DELETE' });
      if (activeSetlist?.id === id) setActiveSetlist(null);
      await loadSetlists();
    } catch {
      setError('Failed to delete setlist');
    }
  };

  const addTrack = async () => {
    if (!activeSetlist || !newTrackTitle.trim()) return;
    const newTrack: SetlistTrack = {
      id: Math.random().toString(36).slice(2, 14),
      title: newTrackTitle.trim(),
      artist: newTrackArtist.trim(),
    };
    const updated = [...activeSetlist.tracks, newTrack];
    try {
      const res = await fetch(`/api/setlists/${activeSetlist.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tracks: updated }),
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setActiveSetlist(data);
      setNewTrackTitle('');
      setNewTrackArtist('');
      await loadSetlists();
    } catch {
      setError('Failed to add track');
    }
  };

  const removeTrack = async (trackId: string) => {
    if (!activeSetlist) return;
    const updated = activeSetlist.tracks.filter(t => t.id !== trackId);
    try {
      const res = await fetch(`/api/setlists/${activeSetlist.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tracks: updated }),
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setActiveSetlist(data);
      await loadSetlists();
    } catch {
      setError('Failed to remove track');
    }
  };

  const moveTrack = async (index: number, direction: 'up' | 'down') => {
    if (!activeSetlist) return;
    const tracks = [...activeSetlist.tracks];
    const newIdx = direction === 'up' ? index - 1 : index + 1;
    if (newIdx < 0 || newIdx >= tracks.length) return;
    [tracks[index], tracks[newIdx]] = [tracks[newIdx], tracks[index]];

    try {
      const res = await fetch(`/api/setlists/${activeSetlist.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tracks }),
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setActiveSetlist(data);
      await loadSetlists();
    } catch {
      setError('Failed to reorder');
    }
  };

  const setTransition = async (fromIdx: number, type: string) => {
    if (!activeSetlist || fromIdx >= activeSetlist.tracks.length - 1) return;
    const from = activeSetlist.tracks[fromIdx];
    const to = activeSetlist.tracks[fromIdx + 1];

    try {
      const res = await fetch(
        `/api/setlists/${activeSetlist.id}/transition?from_track=${from.id}&to_track=${to.id}&transition_type=${type}`,
        { method: 'POST' }
      );
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setActiveSetlist(data);
    } catch {
      setError('Failed to set transition');
    }
  };

  const getTransitionType = (fromIdx: number): string => {
    if (!activeSetlist || fromIdx >= activeSetlist.tracks.length - 1) return 'crossfade';
    const from = activeSetlist.tracks[fromIdx];
    const to = activeSetlist.tracks[fromIdx + 1];
    const key = `${from.id}->${to.id}`;
    return activeSetlist.transitions[key]?.type || 'crossfade';
  };

  const handleBuildAvc = async () => {
    if (!activeSetlist) return;
    setBuilding(true);
    setBuildResult('');
    try {
      const res = await fetch(`/api/setlists/${activeSetlist.id}/build-avc`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setBuildResult(`Built AVC: ${data.track_count} tracks, ${data.transition_count} transitions`);
      } else {
        setBuildResult('Build failed');
      }
    } catch {
      setBuildResult('Build failed');
    }
    setBuilding(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Setlists</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Setlist
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Setlist list */}
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Your Setlists</h2>
          {setlists.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <ListMusic className="w-10 h-10 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No setlists yet</p>
            </div>
          ) : (
            setlists.map(s => (
              <div
                key={s.id}
                className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                  activeSetlist?.id === s.id
                    ? 'bg-[rgba(79,195,247,0.08)] border-[#4FC3F7]/30'
                    : 'bg-gray-800/60 border-gray-700/50 hover:border-gray-600/50'
                }`}
                onClick={() => setActiveSetlist(s)}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-white">{s.name}</h3>
                    <p className="text-xs text-gray-500">{s.tracks.length} tracks</p>
                  </div>
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(s.id); }}
                    className="p-1 text-gray-600 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Active setlist editor */}
        <div className="lg:col-span-2">
          {!activeSetlist ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500 bg-gray-800/30 rounded-xl border border-gray-700/30">
              <ListMusic className="w-12 h-12 mb-3 opacity-30" />
              <p className="text-lg font-medium text-gray-400">Select a setlist to edit</p>
              <p className="text-sm mt-1">Or create a new one to get started</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-medium text-white">{activeSetlist.name}</h2>
                <button
                  onClick={handleBuildAvc}
                  disabled={building || activeSetlist.tracks.length === 0}
                  className="flex items-center gap-2 px-3 py-1.5 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors text-sm disabled:opacity-50"
                >
                  <Hammer className="w-3.5 h-3.5" />
                  {building ? 'Building...' : 'Build .avc'}
                </button>
              </div>
              {buildResult && (
                <p className="text-xs text-green-400">{buildResult}</p>
              )}

              {/* Track list with transitions */}
              <div className="space-y-1">
                {activeSetlist.tracks.map((track, i) => (
                  <div key={track.id}>
                    <div className="flex items-center gap-2 bg-gray-800/60 border border-gray-700/50 rounded-lg p-3">
                      <div className="flex flex-col gap-0.5">
                        <button
                          onClick={() => moveTrack(i, 'up')}
                          disabled={i === 0}
                          className="text-gray-600 hover:text-gray-300 disabled:opacity-20 transition-colors"
                        >
                          <ChevronUp className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => moveTrack(i, 'down')}
                          disabled={i === activeSetlist.tracks.length - 1}
                          className="text-gray-600 hover:text-gray-300 disabled:opacity-20 transition-colors"
                        >
                          <ChevronDown className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <span className="text-xs text-gray-600 w-6 text-center">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-white truncate">{track.title}</p>
                        <p className="text-xs text-gray-500 truncate">{track.artist}</p>
                      </div>
                      <button
                        onClick={() => removeTrack(track.id)}
                        className="p-1 text-gray-600 hover:text-red-400 transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {i < activeSetlist.tracks.length - 1 && (
                      <div className="flex items-center gap-2 py-1 px-6">
                        <ArrowRight className="w-3 h-3 text-gray-600" />
                        <select
                          value={getTransitionType(i)}
                          onChange={e => setTransition(i, e.target.value)}
                          className="px-2 py-1 bg-gray-900/50 border border-gray-700/30 rounded text-xs text-gray-400 focus:outline-none focus:border-[#4FC3F7]"
                        >
                          {TRANSITION_TYPES.map(t => (
                            <option key={t} value={t}>{TRANSITION_LABELS[t]}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Add track form */}
              <div className="bg-gray-800/40 border border-gray-700/30 rounded-lg p-3 space-y-2">
                <h3 className="text-xs text-gray-500 uppercase tracking-wider">Add Track</h3>
                <div className="flex gap-2">
                  <input
                    value={newTrackTitle}
                    onChange={e => setNewTrackTitle(e.target.value)}
                    placeholder="Track title"
                    className="flex-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
                    onKeyDown={e => e.key === 'Enter' && addTrack()}
                  />
                  <input
                    value={newTrackArtist}
                    onChange={e => setNewTrackArtist(e.target.value)}
                    placeholder="Artist"
                    className="w-40 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
                    onKeyDown={e => e.key === 'Enter' && addTrack()}
                  />
                  <button
                    onClick={addTrack}
                    disabled={!newTrackTitle.trim()}
                    className="px-3 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {showCreate && (
        <CreateSetlistModal
          onClose={() => setShowCreate(false)}
          onCreated={(name, desc) => handleCreate(name, desc)}
        />
      )}
    </div>
  );
}

function CreateSetlistModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (name: string, desc: string) => void;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">New Setlist</h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Name</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Friday Night Set"
              autoFocus
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
              onKeyDown={e => e.key === 'Enter' && name.trim() && onCreated(name, desc)}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <input
              value={desc}
              onChange={e => setDesc(e.target.value)}
              placeholder="2-hour house set at Venue X"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
        </div>
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors">Cancel</button>
          <button
            onClick={() => name.trim() && onCreated(name, desc)}
            disabled={!name.trim()}
            className="px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors text-sm disabled:opacity-50"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
