import { useState, useEffect } from 'react';
import {
  Star,
  Plus,
  Trash2,
  Copy,
  Save,
  X,
  Search,
  Palette,
  Sparkles,
} from 'lucide-react';

interface Preset {
  id: string;
  name: string;
  description: string;
  category: string;
  prompt: string;
  model: string;
  motion_settings: Record<string, unknown>;
  style_reference: string;
  color_palette: string[];
  brand_overrides: Record<string, unknown>;
  thumbnail_url: string;
  use_count: number;
  is_favorite: boolean;
  created_at: string;
  updated_at: string;
}

const CATEGORIES = ['user', 'genre', 'mood', 'effect', 'template'];

async function fetchPresets(params?: Record<string, string>): Promise<{ presets: Preset[]; total: number }> {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`/api/presets${qs}`);
  if (!res.ok) throw new Error('Failed to load presets');
  return res.json();
}

export default function Presets() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingPreset, setEditingPreset] = useState<Preset | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadPresets = async () => {
    try {
      const params: Record<string, string> = {};
      if (filterCategory) params.category = filterCategory;
      if (favoritesOnly) params.favorites_only = 'true';
      const data = await fetchPresets(params);
      setPresets(data.presets);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load presets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPresets();
  }, [filterCategory, favoritesOnly]);

  const handleToggleFavorite = async (id: string) => {
    try {
      await fetch(`/api/presets/${id}/favorite`, { method: 'POST' });
      setPresets(prev =>
        prev.map(p => (p.id === id ? { ...p, is_favorite: !p.is_favorite } : p))
      );
    } catch {
      setError('Failed to toggle favorite');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this preset?')) return;
    try {
      await fetch(`/api/presets/${id}`, { method: 'DELETE' });
      setPresets(prev => prev.filter(p => p.id !== id));
    } catch {
      setError('Failed to delete preset');
    }
  };

  const handleDuplicate = async (preset: Preset) => {
    try {
      const res = await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `${preset.name} (copy)`,
          description: preset.description,
          category: preset.category,
          prompt: preset.prompt,
          model: preset.model,
          motion_settings: preset.motion_settings,
          style_reference: preset.style_reference,
          color_palette: preset.color_palette,
          brand_overrides: preset.brand_overrides,
        }),
      });
      if (!res.ok) throw new Error('Failed to duplicate');
      await loadPresets();
    } catch {
      setError('Failed to duplicate preset');
    }
  };

  const filtered = presets.filter(p => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      p.description.toLowerCase().includes(q) ||
      p.prompt.toLowerCase().includes(q)
    );
  });

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
        <div>
          <h1 className="text-2xl font-semibold text-white">Visual Presets</h1>
          <p className="text-sm text-gray-500 mt-1">{total} presets saved</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Preset
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search presets..."
            className="w-full pl-9 pr-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <select
          value={filterCategory}
          onChange={e => setFilterCategory(e.target.value)}
          className="px-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
        >
          <option value="">All Categories</option>
          {CATEGORIES.map(c => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
          ))}
        </select>
        <button
          onClick={() => setFavoritesOnly(!favoritesOnly)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors ${
            favoritesOnly
              ? 'bg-yellow-900/30 border-yellow-700/50 text-yellow-400'
              : 'bg-gray-800/60 border-gray-700/50 text-gray-400 hover:text-gray-200'
          }`}
        >
          <Star className={`w-4 h-4 ${favoritesOnly ? 'fill-yellow-400' : ''}`} />
          Favorites
        </button>
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Sparkles className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">No presets yet</p>
          <p className="text-sm mt-1">Save a generation result as a preset, or create one from scratch.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(preset => (
            <div
              key={preset.id}
              className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4 space-y-3 hover:border-gray-600/50 transition-colors cursor-pointer"
              onClick={() => setEditingPreset(preset)}
            >
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-medium text-white truncate">{preset.name}</h3>
                  <p className="text-xs text-gray-500 truncate">{preset.description || 'No description'}</p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); handleToggleFavorite(preset.id); }}
                  className="p-1 hover:bg-gray-700/50 rounded transition-colors ml-2 flex-shrink-0"
                >
                  <Star className={`w-4 h-4 ${preset.is_favorite ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'}`} />
                </button>
              </div>

              {/* Prompt preview */}
              {preset.prompt && (
                <p className="text-xs text-gray-400 line-clamp-2">{preset.prompt}</p>
              )}

              {/* Color palette */}
              {preset.color_palette && preset.color_palette.length > 0 && (
                <div className="flex gap-1">
                  {(preset.color_palette as string[]).slice(0, 6).map((color, i) => (
                    <div
                      key={i}
                      className="w-5 h-5 rounded-full border border-gray-700"
                      style={{ backgroundColor: typeof color === 'string' ? color : '#333' }}
                    />
                  ))}
                </div>
              )}

              {/* Footer */}
              <div className="flex items-center justify-between text-xs text-gray-500">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-gray-900/50 rounded-full">{preset.category}</span>
                  {preset.model && <span>{preset.model}</span>}
                </div>
                <div className="flex items-center gap-1">
                  <span>Used {preset.use_count}x</span>
                  <button
                    onClick={e => { e.stopPropagation(); handleDuplicate(preset); }}
                    className="p-1 hover:text-gray-300 transition-colors"
                    title="Duplicate"
                  >
                    <Copy className="w-3 h-3" />
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(preset.id); }}
                    className="p-1 hover:text-red-400 transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create / Edit Modal */}
      {(showCreate || editingPreset) && (
        <PresetModal
          preset={editingPreset}
          onClose={() => { setShowCreate(false); setEditingPreset(null); }}
          onSaved={() => { setShowCreate(false); setEditingPreset(null); loadPresets(); }}
        />
      )}
    </div>
  );
}

function PresetModal({
  preset,
  onClose,
  onSaved,
}: {
  preset: Preset | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!preset;
  const [name, setName] = useState(preset?.name || '');
  const [description, setDescription] = useState(preset?.description || '');
  const [category, setCategory] = useState(preset?.category || 'user');
  const [prompt, setPrompt] = useState(preset?.prompt || '');
  const [model, setModel] = useState(preset?.model || '');
  const [colorInput, setColorInput] = useState(
    (preset?.color_palette || []).join(', ')
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    setSaving(true);
    setError('');

    const colors = colorInput
      .split(',')
      .map(c => c.trim())
      .filter(c => c);

    const body = { name, description, category, prompt, model, color_palette: colors };

    try {
      const url = isEdit ? `/api/presets/${preset!.id}` : '/api/presets';
      const method = isEdit ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Save failed');
      onSaved();
    } catch {
      setError('Failed to save preset');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-lg space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">
            {isEdit ? 'Edit Preset' : 'New Preset'}
          </h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Name</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g., Neon Geometry v2"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Brief description of the visual style"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Category</label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              >
                {CATEGORIES.map(c => (
                  <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Model</label>
              <input
                value={model}
                onChange={e => setModel(e.target.value)}
                placeholder="e.g., wan21"
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Prompt</label>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Full generation prompt for this style..."
              rows={4}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7] resize-y"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Color Palette (comma-separated hex)</label>
            <input
              value={colorInput}
              onChange={e => setColorInput(e.target.value)}
              placeholder="#4FC3F7, #E040FB, #FFD54F"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
            {colorInput && (
              <div className="flex gap-1 mt-2">
                {colorInput.split(',').map((c, i) => {
                  const hex = c.trim();
                  return hex ? (
                    <div
                      key={i}
                      className="w-6 h-6 rounded-full border border-gray-700"
                      style={{ backgroundColor: hex }}
                    />
                  ) : null;
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-3 justify-end pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors text-sm disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving...' : isEdit ? 'Update' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
