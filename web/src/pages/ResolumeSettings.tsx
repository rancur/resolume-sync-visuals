import { useState, useEffect } from 'react';
import {
  Save,
  Monitor,
  Layers,
  Play,
  FileOutput,
  Eye,
  Loader2,
  Hammer,
  Send,
  CheckCircle,
  XCircle,
} from 'lucide-react';

interface ResolumeConfig {
  composition_name: string;
  num_decks: number;
  layer_mapping: Record<string, number>;
  transport_mode: string;
  resolution: string;
  clip_naming_format: string;
  output_path: string;
}

const RESOLUTIONS = ['1920x1080', '3840x2160'];
const TRANSPORT_MODES = ['Denon', 'BPM Sync', 'Timeline'];
const CLIP_FORMATS = [
  '{artist} - {title}',
  '{title} - {artist}',
  '{title}',
  'Deck{deck}_{title}',
];

const defaultConfig: ResolumeConfig = {
  composition_name: 'My Show',
  num_decks: 4,
  layer_mapping: { '1': 1, '2': 2, '3': 3, '4': 4 },
  transport_mode: 'Denon',
  resolution: '1920x1080',
  clip_naming_format: '{artist} - {title}',
  output_path: '/volume1/media/visuals/resolume',
};

function ActionButton({
  label,
  icon: Icon,
  onClick,
  variant = 'secondary',
}: {
  label: string;
  icon: React.ElementType;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
}) {
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'error'>('idle');

  const handleClick = async () => {
    setState('working');
    try {
      await onClick();
      setState('done');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 3000);
  };

  const baseClass =
    variant === 'primary'
      ? 'bg-[#4FC3F7] text-gray-900 hover:bg-[#81D4FA]'
      : 'bg-gray-700/50 hover:bg-gray-700 text-gray-300';

  return (
    <button
      onClick={handleClick}
      disabled={state === 'working'}
      className={`flex items-center gap-2 px-4 py-2.5 font-medium rounded-lg transition-colors disabled:opacity-50 ${baseClass}`}
    >
      {state === 'working' && <Loader2 className="w-4 h-4 animate-spin" />}
      {state === 'done' && <CheckCircle className="w-4 h-4 text-green-400" />}
      {state === 'error' && <XCircle className="w-4 h-4 text-red-400" />}
      {state === 'idle' && <Icon className="w-4 h-4" />}
      {state === 'working' ? 'Working...' : state === 'done' ? 'Done!' : state === 'error' ? 'Failed' : label}
    </button>
  );
}

function AvcPreview({ config }: { config: ResolumeConfig }) {
  const [w, h] = config.resolution.split('x').map(Number);
  const layers = Array.from({ length: config.num_decks }, (_, i) => {
    const layerNum = config.layer_mapping[String(i + 1)] || i + 1;
    return { deck: i + 1, layer: layerNum };
  });

  return (
    <div className="font-mono text-xs text-gray-400 bg-gray-950 rounded-lg p-4 overflow-x-auto whitespace-pre">
      {`<composition name="${config.composition_name}" width="${w}" height="${h}">\n`}
      {layers.map((l) => (
        <span key={l.deck}>
          {`  <layer id="${l.layer}" name="Deck ${l.deck}">\n`}
          {`    <clip name="${config.clip_naming_format.replace('{artist}', 'Artist').replace('{title}', 'Track').replace('{deck}', String(l.deck))}" />\n`}
          {`    <transport mode="${config.transport_mode}" />\n`}
          {`  </layer>\n`}
        </span>
      ))}
      {`</composition>`}
    </div>
  );
}

export default function ResolumeSettings() {
  const [config, setConfig] = useState<ResolumeConfig>(defaultConfig);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRebuild, setAutoRebuild] = useState(true);

  useEffect(() => {
    fetch('/api/resolume/settings')
      .then((r) => r.json())
      .then((data) => {
        if (data && data.composition_name) setConfig(data);
      })
      .catch(() => {});
    fetch('/api/resolume/auto-rebuild')
      .then((r) => r.json())
      .then((data) => setAutoRebuild(data.auto_rebuild ?? true))
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/resolume/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
    setSaving(false);
  };

  const handleRebuild = async () => {
    const res = await fetch('/api/resolume/rebuild', { method: 'POST' });
    if (!res.ok) throw new Error(`Rebuild failed: ${res.status}`);
  };

  const handlePush = async () => {
    const res = await fetch('/api/resolume/push', { method: 'POST' });
    if (!res.ok) throw new Error(`Push failed: ${res.status}`);
  };

  const update = (key: keyof ResolumeConfig, val: unknown) => {
    setConfig((c) => ({ ...c, [key]: val }));
  };

  const updateLayerMapping = (deck: number, layer: number) => {
    setConfig((c) => ({
      ...c,
      layer_mapping: { ...c.layer_mapping, [String(deck)]: layer },
    }));
  };

  return (
    <div className="p-6 max-w-4xl space-y-8">
      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">
            Dismiss
          </button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Resolume Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saved ? 'Saved!' : saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {/* Composition */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Monitor className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Composition</h2>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Composition Name</label>
            <input
              value={config.composition_name}
              onChange={(e) => update('composition_name', e.target.value)}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Resolution</label>
            <select
              value={config.resolution}
              onChange={(e) => update('resolution', e.target.value)}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            >
              {RESOLUTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* Deck Configuration */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Layers className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Deck Configuration</h2>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Number of Denon Decks</label>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={1}
              max={4}
              value={config.num_decks}
              onChange={(e) => {
                const n = Number(e.target.value);
                update('num_decks', n);
                // Auto-create layer mappings for new decks
                const newMapping: Record<string, number> = {};
                for (let i = 1; i <= n; i++) {
                  newMapping[String(i)] = config.layer_mapping[String(i)] || i;
                }
                update('layer_mapping', newMapping);
              }}
              className="flex-1 accent-[#4FC3F7]"
            />
            <span className="text-sm text-gray-300 w-16 text-center font-medium">
              {config.num_decks} deck{config.num_decks > 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-xs text-gray-500 block">Layer Mapping</label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Array.from({ length: config.num_decks }, (_, i) => i + 1).map((deck) => (
              <div key={deck} className="p-3 bg-gray-900/40 rounded-lg">
                <span className="text-xs text-gray-400 block mb-1">Deck {deck}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">Layer</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={config.layer_mapping[String(deck)] || deck}
                    onChange={(e) => updateLayerMapping(deck, Number(e.target.value))}
                    className="w-16 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Transport & Clips */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Play className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Transport & Clips</h2>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Default Transport Mode</label>
            <select
              value={config.transport_mode}
              onChange={(e) => update('transport_mode', e.target.value)}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            >
              {TRANSPORT_MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Clip Naming Format</label>
            <select
              value={config.clip_naming_format}
              onChange={(e) => update('clip_naming_format', e.target.value)}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            >
              {CLIP_FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* Output */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <FileOutput className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Output</h2>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Output Path on NAS</label>
          <input
            value={config.output_path}
            onChange={(e) => update('output_path', e.target.value)}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
      </section>

      {/* Auto-Rebuild */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Hammer className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Auto-Rebuild</h2>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-300">Rebuild show after each generation</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Automatically regenerates the .avc composition when a new track visual is generated.
            </p>
          </div>
          <button
            onClick={async () => {
              const next = !autoRebuild;
              setAutoRebuild(next);
              try {
                await fetch(`/api/resolume/auto-rebuild?enabled=${next}`, { method: 'PUT' });
              } catch {}
            }}
            className={`relative w-12 h-6 rounded-full transition-colors ${
              autoRebuild ? 'bg-[#4FC3F7]' : 'bg-gray-600'
            }`}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                autoRebuild ? 'translate-x-6' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>
      </section>

      {/* AVC Preview */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Eye className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">AVC Structure Preview</h2>
        </div>
        <AvcPreview config={config} />
      </section>

      {/* Actions */}
      <div className="flex gap-3">
        <ActionButton label="Rebuild .avc" icon={Hammer} onClick={handleRebuild} variant="primary" />
        <ActionButton label="Push to Resolume" icon={Send} onClick={handlePush} />
      </div>
    </div>
  );
}
