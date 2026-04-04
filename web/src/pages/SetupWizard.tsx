import { useState, useEffect } from 'react';
import {
  ChevronRight,
  ChevronLeft,
  CheckCircle,
  XCircle,
  Loader2,
  Key,
  HardDrive,
  Music,
  Monitor,
  Rocket,
  AlertTriangle,
  HelpCircle,
  ExternalLink,
} from 'lucide-react';
import { api } from '../api/client';

interface StepProps {
  onNext: () => void;
  onBack?: () => void;
}

function HelpTip({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-block ml-1">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen(!open)}
        className="text-gray-500 hover:text-gray-300 transition-colors"
      >
        <HelpCircle className="w-3.5 h-3.5 inline" />
      </button>
      {open && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 bg-gray-900 border border-gray-600 rounded-lg text-xs text-gray-300 shadow-xl">
          {children}
        </div>
      )}
    </div>
  );
}

function TestButton({
  label,
  onTest,
  disabled,
}: {
  label: string;
  onTest: () => Promise<boolean>;
  disabled?: boolean;
}) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<null | boolean>(null);
  const [error, setError] = useState('');

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    setError('');
    try {
      const success = await onTest();
      setResult(success);
      if (!success) setError('Connection failed. Check your settings and try again.');
    } catch (e: any) {
      setResult(false);
      setError(e?.message || 'Connection test failed unexpectedly.');
    }
    setTesting(false);
  };

  return (
    <div>
      <button
        onClick={handleTest}
        disabled={testing || disabled}
        className="flex items-center gap-2 px-4 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors disabled:opacity-50"
      >
        {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
        {result === true && <CheckCircle className="w-4 h-4 text-green-400" />}
        {result === false && <XCircle className="w-4 h-4 text-red-400" />}
        {label}
      </button>
      {result === true && (
        <p className="text-xs text-green-400 mt-1.5">Connected successfully.</p>
      )}
      {result === false && error && (
        <p className="text-xs text-red-400 mt-1.5 flex items-start gap-1">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          {error}
        </p>
      )}
    </div>
  );
}

// Step 1: API Keys
function ApiKeysStep({ onNext }: StepProps) {
  const [fal, setFal] = useState('');
  const [openai, setOpenai] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const canProceed = fal.length > 0 && openai.length > 0;

  const handleNext = async () => {
    setError('');
    setSaving(true);
    try {
      await api.saveSettings({
        api_keys: { fal, openai, replicate: '', runway: '' },
        connections: {
          lexicon_host: '', lexicon_port: 0,
          nas_host: '', nas_path: '',
          resolume_host: '', resolume_port: 0,
        },
        log_retention_days: 30,
      });
    } catch (e: any) {
      // Non-blocking: keys will be set properly on the settings page
      setError('Settings could not be saved yet. You can update them later on the Settings page.');
    }
    setSaving(false);
    onNext();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[rgba(79,195,247,0.15)] flex items-center justify-center">
          <Key className="w-5 h-5 text-[#4FC3F7]" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">API Keys</h2>
          <p className="text-sm text-gray-400">Required for AI video generation</p>
        </div>
      </div>

      <div className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-4 text-xs text-gray-400 space-y-2">
        <p>RSV uses AI models to generate visuals for each track in your DJ library. You need API keys from at least two providers:</p>
        <ul className="list-disc list-inside space-y-1 ml-1">
          <li><strong className="text-gray-300">fal.ai</strong> - Video generation (Kling, Minimax, etc.)</li>
          <li><strong className="text-gray-300">OpenAI</strong> - Image generation and audio analysis</li>
        </ul>
        <p>Keys are stored locally and never sent to third parties.</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            fal.ai API Key <span className="text-red-400">*</span>
            <HelpTip>
              Sign up at fal.ai, go to Dashboard, then Keys. Create a new key with full access. Starts with "fal_".
            </HelpTip>
          </label>
          <input
            type="password"
            value={fal}
            onChange={(e) => setFal(e.target.value)}
            placeholder="fal_..."
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
          <p className="text-xs text-gray-600 mt-1">
            Get your key at{' '}
            <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noreferrer" className="text-[#4FC3F7] hover:underline inline-flex items-center gap-0.5">
              fal.ai/dashboard/keys <ExternalLink className="w-3 h-3" />
            </a>
          </p>
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            OpenAI API Key <span className="text-red-400">*</span>
            <HelpTip>
              Go to platform.openai.com, API Keys section. Create a new secret key. Starts with "sk-".
            </HelpTip>
          </label>
          <input
            type="password"
            value={openai}
            onChange={(e) => setOpenai(e.target.value)}
            placeholder="sk-..."
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
          <p className="text-xs text-gray-600 mt-1">
            Get your key at{' '}
            <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" className="text-[#4FC3F7] hover:underline inline-flex items-center gap-0.5">
              platform.openai.com/api-keys <ExternalLink className="w-3 h-3" />
            </a>
          </p>
        </div>
      </div>

      {error && (
        <p className="text-xs text-yellow-400 flex items-start gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          {error}
        </p>
      )}

      <div className="flex justify-between pt-2">
        <p className="text-xs text-gray-600 self-center">
          Keys can also be injected at runtime via <code className="text-gray-500">op run</code> or environment variables.
        </p>
        <button
          onClick={handleNext}
          disabled={!canProceed || saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Step 2: NAS Connection
function NasStep({ onNext, onBack }: StepProps) {
  const [host, setHost] = useState('');
  const [port, setPort] = useState('7844');
  const [user, setUser] = useState('');
  const [sshKey, setSshKey] = useState('~/.ssh/id_ed25519');

  const canProceed = host.length > 0 && user.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[rgba(79,195,247,0.15)] flex items-center justify-center">
          <HardDrive className="w-5 h-5 text-[#4FC3F7]" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">NAS Connection</h2>
          <p className="text-sm text-gray-400">Where generated videos and music files are stored</p>
        </div>
      </div>

      <div className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-4 text-xs text-gray-400 space-y-2">
        <p>RSV stores generated videos on your NAS (Synology, QNAP, etc.) via SSH. The NAS should have:</p>
        <ul className="list-disc list-inside space-y-1 ml-1">
          <li>SSH enabled on the configured port</li>
          <li>A user account with write access to the video output directory</li>
          <li>An SSH key authorized for password-less login</li>
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            Host <span className="text-red-400">*</span>
            <HelpTip>IP address or hostname of your NAS. Find this in your NAS admin panel under Network.</HelpTip>
          </label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="your-nas-ip"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            SSH Port
            <HelpTip>Default SSH port is 22. Synology often uses a custom port like 7844.</HelpTip>
          </label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="7844"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            Username <span className="text-red-400">*</span>
            <HelpTip>The SSH user on your NAS. Needs read/write access to the video output directory.</HelpTip>
          </label>
          <input
            value={user}
            onChange={(e) => setUser(e.target.value)}
            placeholder="username"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            SSH Key Path
            <HelpTip>Path to your SSH private key. Must be authorized on the NAS (added to ~/.ssh/authorized_keys).</HelpTip>
          </label>
          <input
            value={sshKey}
            onChange={(e) => setSshKey(e.target.value)}
            placeholder="~/.ssh/id_ed25519"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
      </div>

      <TestButton
        label="Test Connection"
        disabled={!canProceed}
        onTest={async () => {
          const result = await api.testConnection('nas');
          return result.connected === true;
        }}
      />

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-5 py-2.5 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Step 3: Lexicon DJ
function LexiconStep({ onNext, onBack }: StepProps) {
  const [host, setHost] = useState('');
  const [port, setPort] = useState('48624');

  const canProceed = host.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[rgba(79,195,247,0.15)] flex items-center justify-center">
          <Music className="w-5 h-5 text-[#4FC3F7]" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">Lexicon DJ</h2>
          <p className="text-sm text-gray-400">Connect to your Lexicon DJ library for track metadata</p>
        </div>
      </div>

      <div className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-4 text-xs text-gray-400 space-y-2">
        <p>Lexicon DJ provides the track library (titles, artists, BPM, key, genre). Make sure Lexicon is running and its API server is enabled.</p>
        <p>In Lexicon: <strong className="text-gray-300">Settings &gt; Advanced &gt; Enable API</strong>.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <label className="text-sm text-gray-400 mb-1.5 block">
            Host <span className="text-red-400">*</span>
            <HelpTip>IP address of the machine running Lexicon DJ. Use the local network IP, not localhost.</HelpTip>
          </label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="your-lexicon-ip"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            Port
            <HelpTip>Default Lexicon API port is 48624. Check Lexicon settings if you changed it.</HelpTip>
          </label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="48624"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
      </div>

      <TestButton
        label="Test Connection"
        disabled={!canProceed}
        onTest={async () => {
          const result = await api.testConnection('lexicon');
          return result.connected === true;
        }}
      />

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-5 py-2.5 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Step 4: Resolume
function ResolumeStep({ onNext, onBack }: StepProps) {
  const [host, setHost] = useState('127.0.0.1');
  const [port, setPort] = useState('8080');

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[rgba(79,195,247,0.15)] flex items-center justify-center">
          <Monitor className="w-5 h-5 text-[#4FC3F7]" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">Resolume Arena</h2>
          <p className="text-sm text-gray-400">Optional -- connect to Resolume for live visual control</p>
        </div>
      </div>

      <div className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-4 text-xs text-gray-400 space-y-2">
        <p>This is optional. RSV can generate .avc composition files and push clips to Resolume Arena via its REST API.</p>
        <p>In Resolume: <strong className="text-gray-300">Preferences &gt; Webserver &gt; Enable</strong>. Default port is 8080.</p>
        <p className="text-gray-500">You can skip this if Resolume is on a different machine or not running yet.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <label className="text-sm text-gray-400 mb-1.5 block">
            Host
            <HelpTip>IP or hostname where Resolume Arena is running. Use 127.0.0.1 if it is on this machine.</HelpTip>
          </label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="127.0.0.1"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1.5 block">
            Port
            <HelpTip>Resolume REST API port. Default is 8080. Check Resolume Preferences &gt; Webserver.</HelpTip>
          </label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="8080"
            className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
          />
        </div>
      </div>

      <TestButton
        label="Test Connection"
        onTest={async () => {
          const result = await api.testConnection('resolume');
          return result.connected === true;
        }}
      />

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-5 py-2.5 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
        <button
          onClick={onNext}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors"
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Step 5: Done
function DoneStep({ onComplete }: { onComplete: () => void }) {
  const [version, setVersion] = useState('');

  useEffect(() => {
    api.getVersion().then(v => setVersion(v.current)).catch(() => {});
  }, []);

  return (
    <div className="space-y-6 text-center py-6">
      <div className="w-16 h-16 rounded-full bg-green-900/30 border border-green-700/50 flex items-center justify-center mx-auto">
        <Rocket className="w-8 h-8 text-green-400" />
      </div>
      <div>
        <h2 className="text-2xl font-semibold text-white">You're All Set</h2>
        <p className="text-gray-400 mt-2 max-w-md mx-auto">
          Configuration complete. You can always update these settings later from the Settings page.
        </p>
        {version && (
          <p className="text-gray-600 text-xs mt-2">RSV v{version}</p>
        )}
      </div>

      <div className="bg-gray-900/50 border border-gray-700/30 rounded-lg p-4 text-xs text-gray-400 max-w-sm mx-auto space-y-2">
        <p className="font-medium text-gray-300">Quick start:</p>
        <ol className="list-decimal list-inside space-y-1 text-left">
          <li>Browse your track library</li>
          <li>Select tracks and generate visuals</li>
          <li>Preview results in the browser</li>
          <li>Export .avc files for Resolume</li>
        </ol>
      </div>

      <button
        onClick={onComplete}
        className="px-8 py-3 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors text-lg"
      >
        Launch Dashboard
      </button>
    </div>
  );
}

const STEPS = [
  { label: 'API Keys', icon: Key },
  { label: 'NAS', icon: HardDrive },
  { label: 'Lexicon', icon: Music },
  { label: 'Resolume', icon: Monitor },
  { label: 'Done', icon: Rocket },
];

export default function SetupWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);

  // Pre-populate from existing settings if partially configured
  useEffect(() => {
    api.getSetupStatus().then(status => {
      // If NAS and Lexicon are already configured, jump to Done
      if (status.sections?.nas?.complete && status.sections?.lexicon?.complete) {
        setStep(4);
      }
    }).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">
            Resolume Sync Visuals
          </h1>
          <p className="text-gray-500 mt-1">First-Run Setup</p>
        </div>

        {/* Progress indicator */}
        <div className="flex items-center justify-center gap-1 mb-8">
          {STEPS.map((s, i) => (
            <div key={s.label} className="flex items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors cursor-pointer ${
                  i < step
                    ? 'bg-green-900/50 text-green-400 border border-green-700/50'
                    : i === step
                    ? 'bg-[rgba(79,195,247,0.15)] text-[#4FC3F7] border border-[#4FC3F7]/30'
                    : 'bg-gray-800 text-gray-600 border border-gray-700/50'
                }`}
                onClick={() => { if (i < step) setStep(i); }}
                title={i < step ? `Go back to ${s.label}` : s.label}
              >
                {i < step ? <CheckCircle className="w-4 h-4" /> : i + 1}
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`w-8 h-0.5 mx-1 transition-colors ${
                    i < step ? 'bg-green-700/50' : 'bg-gray-800'
                  }`}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step content */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-6">
          {step === 0 && <ApiKeysStep onNext={() => setStep(1)} />}
          {step === 1 && <NasStep onNext={() => setStep(2)} onBack={() => setStep(0)} />}
          {step === 2 && <LexiconStep onNext={() => setStep(3)} onBack={() => setStep(1)} />}
          {step === 3 && <ResolumeStep onNext={() => setStep(4)} onBack={() => setStep(2)} />}
          {step === 4 && <DoneStep onComplete={onComplete} />}
        </div>

        {/* Step label */}
        <p className="text-center text-xs text-gray-600 mt-4">
          Step {step + 1} of {STEPS.length}: {STEPS[step].label}
        </p>

        {/* Skip setup link */}
        <div className="text-center mt-3">
          <button
            onClick={async () => {
              try { await api.dismissSetup(); } catch { /* best effort */ }
              onComplete();
            }}
            className="text-xs text-gray-600 hover:text-gray-400 underline transition-colors"
          >
            Skip setup -- system is already configured
          </button>
        </div>
      </div>
    </div>
  );
}
