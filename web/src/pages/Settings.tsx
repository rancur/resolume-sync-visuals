import { useState, useEffect } from 'react';
import {
  Save,
  Eye,
  EyeOff,
  CheckCircle,
  XCircle,
  Loader2,
  Key,
  Plug,
  Clock,
  Download,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  DollarSign,
  AlertTriangle,
} from 'lucide-react';
import { api, type AppSettings, type CostProtectionSettings } from '../api/client';

function MaskedInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="relative">
      <input
        type={revealed ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pr-10 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
      />
      <button
        type="button"
        onClick={() => setRevealed(!revealed)}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-gray-300"
      >
        {revealed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
}

function TestButton({ type }: { type: 'lexicon' | 'nas' | 'resolume' }) {
  const [state, setState] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');

  const handleTest = async () => {
    setState('testing');
    try {
      const result = await api.testConnection(type);
      setState(result.connected || result.ok ? 'ok' : 'fail');
    } catch {
      setState('fail');
    }
    setTimeout(() => setState('idle'), 3000);
  };

  return (
    <button
      onClick={handleTest}
      disabled={state === 'testing'}
      className="px-3 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 text-xs rounded-lg transition-colors flex items-center gap-1.5 disabled:opacity-50"
    >
      {state === 'testing' && <Loader2 className="w-3 h-3 animate-spin" />}
      {state === 'ok' && <CheckCircle className="w-3 h-3 text-green-400" />}
      {state === 'fail' && <XCircle className="w-3 h-3 text-red-400" />}
      {state === 'idle' && 'Test'}
      {state === 'testing' && 'Testing...'}
      {state === 'ok' && 'Connected'}
      {state === 'fail' && 'Failed'}
    </button>
  );
}

const defaultSettings: AppSettings = {
  api_keys: { openai: '', replicate: '', runway: '', fal: '' },
  connections: {
    lexicon_host: 'localhost',
    lexicon_port: 8080,
    nas_host: 'localhost',
    nas_path: '/media/visuals',
    resolume_host: 'localhost',
    resolume_port: 7000,
  },
  log_retention_days: 30,
};

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings()
      .then(setSettings)
      .catch(() => setSettings(defaultSettings));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.saveSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(`Failed to save settings: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    setSaving(false);
  };

  const updateKey = (key: keyof AppSettings['api_keys'], val: string) => {
    setSettings((s) => ({
      ...s,
      api_keys: { ...s.api_keys, [key]: val },
    }));
  };

  const updateConn = (key: keyof AppSettings['connections'], val: string | number) => {
    setSettings((s) => ({
      ...s,
      connections: { ...s.connections, [key]: val },
    }));
  };

  return (
    <div className="p-6 max-w-3xl space-y-8">
      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saved ? 'Saved!' : saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {/* API Keys */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Key className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            API Keys
          </h2>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">OpenAI</label>
            <MaskedInput
              value={settings.api_keys.openai || ''}
              onChange={(v) => updateKey('openai', v)}
              placeholder="sk-..."
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Replicate</label>
            <MaskedInput
              value={settings.api_keys.replicate || ''}
              onChange={(v) => updateKey('replicate', v)}
              placeholder="r8_..."
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Runway</label>
            <MaskedInput
              value={settings.api_keys.runway || ''}
              onChange={(v) => updateKey('runway', v)}
              placeholder="rw_..."
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">fal.ai</label>
            <MaskedInput
              value={settings.api_keys.fal || ''}
              onChange={(v) => updateKey('fal', v)}
              placeholder="fal_..."
            />
          </div>
        </div>
      </section>

      {/* Connections */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Plug className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Connections
          </h2>
        </div>

        {/* Lexicon */}
        <div className="p-3 bg-gray-900/40 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-300 font-medium">Lexicon (Audio Analysis)</span>
            <TestButton type="lexicon" />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2">
              <label className="text-xs text-gray-500 mb-1 block">Host</label>
              <input
                value={settings.connections.lexicon_host}
                onChange={(e) => updateConn('lexicon_host', e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Port</label>
              <input
                type="number"
                value={settings.connections.lexicon_port}
                onChange={(e) => updateConn('lexicon_port', Number(e.target.value))}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
          </div>
        </div>

        {/* NAS */}
        <div className="p-3 bg-gray-900/40 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-300 font-medium">NAS Storage</span>
            <TestButton type="nas" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Host</label>
              <input
                value={settings.connections.nas_host}
                onChange={(e) => updateConn('nas_host', e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Path</label>
              <input
                value={settings.connections.nas_path}
                onChange={(e) => updateConn('nas_path', e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
          </div>
        </div>

        {/* Resolume */}
        <div className="p-3 bg-gray-900/40 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-300 font-medium">Resolume Arena</span>
            <TestButton type="resolume" />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2">
              <label className="text-xs text-gray-500 mb-1 block">Host</label>
              <input
                value={settings.connections.resolume_host}
                onChange={(e) => updateConn('resolume_host', e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Port</label>
              <input
                type="number"
                value={settings.connections.resolume_port}
                onChange={(e) => updateConn('resolume_port', Number(e.target.value))}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Notifications */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Plug className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Notifications
          </h2>
        </div>
        <div className="p-3 bg-gray-900/40 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-300 font-medium">Discord Webhook</span>
            <TestButton type={'lexicon' as any} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Webhook URL</label>
            <MaskedInput
              value={(settings as any).discord_webhook_url || ''}
              onChange={(v) => setSettings((s: any) => ({ ...s, discord_webhook_url: v }))}
              placeholder="https://discord.com/api/webhooks/..."
            />
            <p className="text-xs text-gray-600 mt-1">
              Receive notifications when generations complete or fail. Leave blank to disable.
            </p>
          </div>
        </div>
      </section>

      {/* Cost Protection */}
      <CostProtectionSection />

      {/* Log Retention */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Clock className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Log Retention
          </h2>
        </div>
        <div className="flex items-center gap-4">
          <input
            type="range"
            min={7}
            max={90}
            value={settings.log_retention_days}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                log_retention_days: Number(e.target.value),
              }))
            }
            className="flex-1 accent-[#4FC3F7]"
          />
          <span className="text-sm text-gray-300 w-20">
            {settings.log_retention_days} days
          </span>
        </div>
      </section>

      {/* Version & Updates */}
      <VersionSection />
    </div>
  );
}

function CostProtectionSection() {
  const [costSettings, setCostSettings] = useState<CostProtectionSettings>({
    cost_cap_per_song: 30,
    cost_auto_downgrade: true,
    cost_confirm_threshold: 20,
  });
  const [costSaving, setCostSaving] = useState(false);
  const [costSaved, setCostSaved] = useState(false);

  useEffect(() => {
    api.getCostProtection().then(setCostSettings).catch(() => {});
  }, []);

  const handleSaveCost = async () => {
    setCostSaving(true);
    try {
      await api.saveCostProtection(costSettings);
      setCostSaved(true);
      setTimeout(() => setCostSaved(false), 2000);
    } catch {
      // ignore
    }
    setCostSaving(false);
  };

  return (
    <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Cost Protection
          </h2>
        </div>
        <button
          onClick={handleSaveCost}
          disabled={costSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
        >
          <Save className="w-3 h-3" />
          {costSaved ? 'Saved!' : costSaving ? 'Saving...' : 'Save'}
        </button>
      </div>

      <div className="p-3 bg-yellow-900/20 border border-yellow-700/30 rounded-lg">
        <div className="flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-yellow-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-yellow-300">
            These settings prevent runaway API costs. A single Veo 2 song can cost $50+.
            The per-song cap stops generation and saves partial results when the limit is reached.
          </p>
        </div>
      </div>

      {/* Per-song cost cap slider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-sm text-gray-300">Per-Song Cost Cap</label>
          <span className="text-sm font-mono text-white">
            ${costSettings.cost_cap_per_song.toFixed(0)}
          </span>
        </div>
        <input
          type="range"
          min={5}
          max={100}
          step={5}
          value={costSettings.cost_cap_per_song}
          onChange={(e) =>
            setCostSettings((s) => ({ ...s, cost_cap_per_song: Number(e.target.value) }))
          }
          className="w-full accent-[#4FC3F7]"
        />
        <div className="flex justify-between text-xs text-gray-600">
          <span>$5</span>
          <span>$50</span>
          <span>$100</span>
        </div>
      </div>

      {/* Auto-downgrade toggle */}
      <div className="flex items-center justify-between p-3 bg-gray-900/40 rounded-lg">
        <div>
          <p className="text-sm text-gray-300">Auto-downgrade model when over budget</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Switches to a cheaper model instead of stopping generation
          </p>
        </div>
        <button
          onClick={() =>
            setCostSettings((s) => ({ ...s, cost_auto_downgrade: !s.cost_auto_downgrade }))
          }
          className={`relative w-11 h-6 rounded-full transition-colors ${
            costSettings.cost_auto_downgrade ? 'bg-[#4FC3F7]' : 'bg-gray-600'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
              costSettings.cost_auto_downgrade ? 'translate-x-5' : ''
            }`}
          />
        </button>
      </div>

      {/* Confirmation threshold */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-sm text-gray-300">Confirm when estimated cost exceeds</label>
          <span className="text-sm font-mono text-white">
            ${costSettings.cost_confirm_threshold.toFixed(0)}
          </span>
        </div>
        <input
          type="range"
          min={5}
          max={50}
          step={5}
          value={costSettings.cost_confirm_threshold}
          onChange={(e) =>
            setCostSettings((s) => ({
              ...s,
              cost_confirm_threshold: Number(e.target.value),
            }))
          }
          className="w-full accent-[#4FC3F7]"
        />
        <p className="text-xs text-gray-500">
          Shows a warning before starting songs estimated above this amount
        </p>
      </div>
    </section>
  );
}

function VersionSection() {
  const [version, setVersion] = useState<{
    current: string;
    latest: string;
    update_available: boolean;
    changelog: string;
    html_url: string;
  } | null>(null);
  const [checking, setChecking] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [updateResult, setUpdateResult] = useState<string | null>(null);

  const checkForUpdates = async () => {
    setChecking(true);
    try {
      const data = await api.getVersion();
      setVersion(data);
    } catch {
      setVersion(null);
    }
    setChecking(false);
  };

  const triggerUpdate = async () => {
    setUpdating(true);
    setUpdateResult(null);
    try {
      const result = await api.triggerUpdate();
      setUpdateResult(result.message);
    } catch (err) {
      setUpdateResult(`Update failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    setUpdating(false);
  };

  useEffect(() => {
    checkForUpdates();
  }, []);

  return (
    <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <Download className="w-4 h-4 text-[#4FC3F7]" />
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
          Version & Updates
        </h2>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-300">
            Current version: <span className="font-mono text-white">{version?.current || '...'}</span>
          </p>
          {version?.update_available && (
            <p className="text-sm text-green-400 mt-1">
              Update available: <span className="font-mono">{version.latest}</span>
            </p>
          )}
          {version && !version.update_available && (
            <p className="text-xs text-gray-500 mt-1">You're on the latest version</p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={checkForUpdates}
            disabled={checking}
            className="flex items-center gap-1.5 px-3 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 text-xs rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${checking ? 'animate-spin' : ''}`} />
            Check for Updates
          </button>

          {version?.update_available && (
            <button
              onClick={triggerUpdate}
              disabled={updating}
              className="flex items-center gap-1.5 px-3 py-2 bg-[#4FC3F7] text-gray-900 text-xs font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
            >
              {updating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
              {updating ? 'Updating...' : 'Update Now'}
            </button>
          )}
        </div>
      </div>

      {updateResult && (
        <div className="p-3 bg-gray-900/50 border border-gray-700/50 rounded-lg text-sm text-gray-300">
          {updateResult}
        </div>
      )}

      {version?.update_available && version.changelog && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider">Changelog</p>
          <div className="p-3 bg-gray-900/50 border border-gray-700/50 rounded-lg text-sm text-gray-400 max-h-40 overflow-y-auto whitespace-pre-wrap">
            {version.changelog}
          </div>
          {version.html_url && (
            <a
              href={version.html_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[#4FC3F7] hover:underline"
            >
              View on GitHub <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      )}
    </section>
  );
}
