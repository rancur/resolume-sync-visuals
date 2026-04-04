import { useState, useEffect } from 'react';
import {
  Radio,
  Send,
  CheckCircle,
  XCircle,
  Loader2,
  Save,
  Zap,
  Sliders,
  RefreshCw,
} from 'lucide-react';

interface OscConfig {
  host: string;
  port: number;
  enabled: boolean;
  mappings: Record<string, string>;
  stagelinq_enabled: boolean;
  stagelinq_interface: string;
}

interface OscPreset {
  name: string;
  description: string;
  mappings: Record<string, string>;
}

const DEFAULT_CONFIG: OscConfig = {
  host: '127.0.0.1',
  port: 7000,
  enabled: false,
  mappings: {},
  stagelinq_enabled: false,
  stagelinq_interface: '',
};

export default function OscControl() {
  const [config, setConfig] = useState<OscConfig>(DEFAULT_CONFIG);
  const [addresses, setAddresses] = useState<Record<string, string>>({});
  const [presets, setPresets] = useState<OscPreset[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
  const [testMessage, setTestMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Quick-send state
  const [sendAddr, setSendAddr] = useState('');
  const [sendValue, setSendValue] = useState(1.0);
  const [sendResult, setSendResult] = useState('');

  useEffect(() => {
    Promise.all([
      fetch('/api/osc/config').then(r => r.json()).then(setConfig).catch(() => {}),
      fetch('/api/osc/addresses').then(r => r.json()).then(d => setAddresses(d.addresses || {})).catch(() => {}),
      fetch('/api/osc/presets').then(r => r.json()).then(d => setPresets(d.presets || [])).catch(() => {}),
    ]);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/osc/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error('Save failed');
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
    setSaving(false);
  };

  const handleTest = async () => {
    setTestStatus('testing');
    try {
      const res = await fetch('/api/osc/test', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setTestStatus('success');
        setTestMessage(data.message);
      } else {
        setTestStatus('error');
        setTestMessage(data.message);
      }
    } catch {
      setTestStatus('error');
      setTestMessage('Network error');
    }
    setTimeout(() => setTestStatus('idle'), 3000);
  };

  const handleSend = async () => {
    if (!sendAddr) return;
    try {
      const res = await fetch('/api/osc/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: sendAddr, value: sendValue }),
      });
      const data = await res.json();
      setSendResult(data.sent ? `Sent to ${data.target}` : data.error || 'Failed');
      setTimeout(() => setSendResult(''), 3000);
    } catch {
      setSendResult('Network error');
    }
  };

  const applyPreset = (preset: OscPreset) => {
    setConfig(c => ({ ...c, mappings: { ...c.mappings, ...preset.mappings } }));
  };

  const updateMapping = (key: string, value: string) => {
    setConfig(c => ({
      ...c,
      mappings: { ...c.mappings, [key]: value },
    }));
  };

  const removeMapping = (key: string) => {
    setConfig(c => {
      const m = { ...c.mappings };
      delete m[key];
      return { ...c, mappings: m };
    });
  };

  const addMapping = () => {
    const key = `custom_${Object.keys(config.mappings).length + 1}`;
    setConfig(c => ({
      ...c,
      mappings: { ...c.mappings, [key]: '' },
    }));
  };

  return (
    <div className="p-6 max-w-4xl space-y-8">
      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">OSC Control</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saved ? 'Saved!' : saving ? 'Saving...' : 'Save Config'}
        </button>
      </div>

      {/* Connection */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Radio className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Connection</h2>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Resolume Host</label>
            <input
              value={config.host}
              onChange={e => setConfig(c => ({ ...c, host: e.target.value }))}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">OSC Port</label>
            <input
              type="number"
              value={config.port}
              onChange={e => setConfig(c => ({ ...c, port: Number(e.target.value) }))}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={e => setConfig(c => ({ ...c, enabled: e.target.checked }))}
                className="accent-[#4FC3F7]"
              />
              Enable real-time OSC streaming
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={config.stagelinq_enabled}
                onChange={e => setConfig(c => ({ ...c, stagelinq_enabled: e.target.checked }))}
                className="accent-[#4FC3F7]"
              />
              StagelinQ bridge
            </label>
          </div>
          <button
            onClick={handleTest}
            disabled={testStatus === 'testing'}
            className="flex items-center gap-2 px-3 py-1.5 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-colors disabled:opacity-50"
          >
            {testStatus === 'testing' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {testStatus === 'success' && <CheckCircle className="w-3.5 h-3.5 text-green-400" />}
            {testStatus === 'error' && <XCircle className="w-3.5 h-3.5 text-red-400" />}
            {testStatus === 'idle' && <Zap className="w-3.5 h-3.5" />}
            {testStatus === 'testing' ? 'Testing...' : testStatus === 'success' ? 'Connected' : testStatus === 'error' ? 'Failed' : 'Test Connection'}
          </button>
        </div>
        {testMessage && (
          <p className={`text-xs ${testStatus === 'success' ? 'text-green-400' : 'text-red-400'}`}>
            {testMessage}
          </p>
        )}
      </section>

      {/* Quick Send */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Send className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Quick Send</h2>
        </div>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs text-gray-500 mb-1 block">OSC Address</label>
            <input
              value={sendAddr}
              onChange={e => setSendAddr(e.target.value)}
              placeholder="/composition/layers/1/video/opacity"
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
          <div className="w-24">
            <label className="text-xs text-gray-500 mb-1 block">Value</label>
            <input
              type="number"
              step={0.1}
              min={0}
              max={1}
              value={sendValue}
              onChange={e => setSendValue(Number(e.target.value))}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
          <button
            onClick={handleSend}
            className="px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        {/* Value slider */}
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={sendValue}
          onChange={e => setSendValue(Number(e.target.value))}
          className="w-full accent-[#4FC3F7] h-1"
        />
        {sendResult && <p className="text-xs text-gray-400">{sendResult}</p>}
      </section>

      {/* Mappings */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-[#4FC3F7]" />
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Parameter Mappings</h2>
          </div>
          <button
            onClick={addMapping}
            className="text-xs text-[#4FC3F7] hover:text-[#81D4FA] transition-colors"
          >
            + Add Mapping
          </button>
        </div>
        <p className="text-xs text-gray-500">Map audio analysis signals to Resolume OSC addresses.</p>
        <div className="space-y-2">
          {Object.entries(config.mappings).map(([key, addr]) => (
            <div key={key} className="flex gap-2 items-center">
              <input
                value={key}
                readOnly
                className="w-36 px-3 py-2 bg-gray-900/50 border border-gray-700/50 rounded-lg text-xs text-gray-400 font-mono"
              />
              <span className="text-gray-600 text-xs">{'->'}</span>
              <input
                value={addr}
                onChange={e => updateMapping(key, e.target.value)}
                placeholder="/composition/..."
                className="flex-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7] font-mono"
              />
              <button
                onClick={() => removeMapping(key)}
                className="px-2 py-2 text-gray-500 hover:text-red-400 transition-colors text-xs"
              >
                x
              </button>
            </div>
          ))}
          {Object.keys(config.mappings).length === 0 && (
            <p className="text-xs text-gray-600">No mappings configured. Apply a preset or add custom mappings.</p>
          )}
        </div>
      </section>

      {/* Presets */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <RefreshCw className="w-4 h-4 text-[#4FC3F7]" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Mapping Presets</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {presets.map(preset => (
            <div
              key={preset.name}
              className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-3 hover:border-gray-600/50 transition-colors cursor-pointer"
              onClick={() => applyPreset(preset)}
            >
              <h3 className="text-sm text-gray-200 font-medium">{preset.name}</h3>
              <p className="text-xs text-gray-500 mt-1">{preset.description}</p>
              <div className="mt-2 text-xs text-gray-600 font-mono">
                {Object.keys(preset.mappings).length} mappings
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Reference */}
      <section className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 space-y-4">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">OSC Address Reference</h2>
        <div className="space-y-1 font-mono text-xs">
          {Object.entries(addresses).map(([name, addr]) => (
            <div
              key={name}
              className="flex justify-between items-center py-1.5 px-2 hover:bg-gray-900/30 rounded cursor-pointer"
              onClick={() => setSendAddr(addr)}
            >
              <span className="text-gray-400">{name.replace(/_/g, ' ')}</span>
              <span className="text-gray-600">{addr}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
