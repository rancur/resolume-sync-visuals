import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Save,
  ChevronDown,
  ChevronRight,
  Palette,
  Eye,
  Music,
  Layers,
  Sliders,
  Monitor,
  Plus,
  Trash2,
  Trees,
  Search,
  Copy,
  Zap,
  X,
} from 'lucide-react';
import { api } from '../api/client';

// ─── Persistent accordion state ─────────────────────────────
const ACCORDION_STORAGE_KEY = 'brand-editor-open-sections';

function loadOpenSections(): Set<string> {
  try {
    const stored = localStorage.getItem(ACCORDION_STORAGE_KEY);
    if (stored) return new Set(JSON.parse(stored));
  } catch {}
  return new Set(['identity']);
}

function saveOpenSections(sections: Set<string>) {
  try {
    localStorage.setItem(ACCORDION_STORAGE_KEY, JSON.stringify([...sections]));
  } catch {}
}

// ─── Accordion ───────────────────────────────────────────────
function Accordion({
  title,
  icon,
  open,
  onToggle,
  badge,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  badge?: string | number;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-gray-700/50 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 bg-gray-800/80 hover:bg-gray-800 transition-colors text-left"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
        )}
        {icon}
        <span className="text-sm font-medium text-gray-200">{title}</span>
        {badge !== undefined && (
          <span className="ml-auto text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">
            {badge}
          </span>
        )}
      </button>
      {open && <div className="p-4 bg-gray-900/40 space-y-4">{children}</div>}
    </div>
  );
}

// ─── Field helpers ───────────────────────────────────────────
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1 block">
        {label}
      </span>
      {children}
    </label>
  );
}

const inputCls =
  'w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7] transition-colors';
const textareaCls = inputCls + ' resize-y min-h-[60px]';

function TextInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="text"
      className={inputCls}
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
    />
  );
}

function TextArea({
  value,
  onChange,
  placeholder,
  rows,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      className={textareaCls}
      rows={rows || 3}
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
    />
  );
}

function ColorPicker({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  label?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative">
        <input
          type="color"
          value={value || '#000000'}
          onChange={(e) => onChange(e.target.value)}
          className="w-10 h-10 rounded-lg border border-gray-700 cursor-pointer bg-transparent [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded-lg [&::-webkit-color-swatch]:border-none"
        />
      </div>
      <div className="flex-1">
        {label && <p className="text-xs text-gray-400 mb-0.5">{label}</p>}
        <input
          type="text"
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-300 font-mono focus:outline-none focus:border-[#4FC3F7]"
        />
      </div>
    </div>
  );
}

function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string | number;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
}) {
  return (
    <select
      className={inputCls}
      value={String(value)}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

// ─── Dynamic list helpers ────────────────────────────────────
function ListOfStrings({
  items,
  onChange,
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
}) {
  const arr = items || [];
  return (
    <div className="space-y-2">
      {arr.map((item, i) => (
        <div key={i} className="flex gap-2">
          <input
            type="text"
            className={inputCls + ' flex-1'}
            value={item}
            onChange={(e) => {
              const next = [...arr];
              next[i] = e.target.value;
              onChange(next);
            }}
            placeholder={placeholder}
          />
          <button
            onClick={() => onChange(arr.filter((_, j) => j !== i))}
            className="p-2 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...arr, ''])}
        className="flex items-center gap-1.5 text-xs text-[#4FC3F7] hover:text-[#81D4FA] transition-colors"
      >
        <Plus className="w-3.5 h-3.5" /> Add
      </button>
    </div>
  );
}

function ListOfColors({
  items,
  onChange,
}: {
  items: string[];
  onChange: (items: string[]) => void;
}) {
  const arr = items || [];
  return (
    <div className="space-y-2">
      {arr.map((item, i) => (
        <div key={i} className="flex gap-2 items-center">
          <div className="flex-1">
            <ColorPicker
              value={item}
              onChange={(v) => {
                const next = [...arr];
                next[i] = v;
                onChange(next);
              }}
            />
          </div>
          <button
            onClick={() => onChange(arr.filter((_, j) => j !== i))}
            className="p-2 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...arr, '#FF00FF'])}
        className="flex items-center gap-1.5 text-xs text-[#4FC3F7] hover:text-[#81D4FA] transition-colors"
      >
        <Plus className="w-3.5 h-3.5" /> Add Color
      </button>
    </div>
  );
}

// ─── Deep set helper ─────────────────────────────────────────
function deepSet(obj: any, path: string[], value: any): any {
  if (path.length === 0) return value;
  const [head, ...rest] = path;
  const clone = Array.isArray(obj) ? [...obj] : { ...obj };
  clone[head] = deepSet(clone[head] ?? {}, rest, value);
  return clone;
}

function deepGet(obj: any, path: string[]): any {
  let cur = obj;
  for (const k of path) {
    if (cur == null) return undefined;
    cur = cur[k];
  }
  return cur;
}

// ─── Genre similarity map for "Copy from similar" ────────────
const GENRE_FAMILIES: Record<string, string[]> = {
  'drum & bass': ['drum and bass', 'liquid dnb', 'neurofunk', 'jungle', 'halftime', 'drum & bass:liquid', 'drum & bass:neuro', 'drum & bass:jump up'],
  'house': ['deep house', 'tech house', 'progressive house', 'acid house', 'funky house', 'afro house', 'minimal house', 'bass house', 'speed garage'],
  'techno': ['hard techno', 'melodic techno', 'industrial', 'minimal'],
  'trance': ['psytrance', 'progressive trance'],
  'dubstep': ['riddim', '140', 'experimental bass'],
  'breaks': ['breakbeat', 'electro', 'footwork'],
  'hard dance': ['hardstyle', 'hardcore'],
  'ambient': ['downtempo', 'chillout', 'lo-fi'],
  'bass': ['uk bass', 'dub', 'grime', 'melodic bass', 'future bass', 'midtempo', 'wave'],
  'garage': ['uk garage', 'future garage', 'jersey', 'speed garage'],
  'retro': ['synthwave', 'retrowave', 'vaporwave', 'electro'],
  'trap': ['trap', 'future bass', 'wave'],
};

function findSimilarGenres(genre: string): string[] {
  const lower = genre.toLowerCase();
  const similar: string[] = [];
  for (const [_family, members] of Object.entries(GENRE_FAMILIES)) {
    if (members.some((m) => m === lower)) {
      similar.push(...members.filter((m) => m !== lower));
    }
  }
  return [...new Set(similar)];
}

// ─── Preview Prompt Modal ────────────────────────────────────
function PreviewPromptModal({
  brandName,
  sections,
  moodKeys,
  genreKeys,
  onClose,
}: {
  brandName: string;
  sections: string[];
  moodKeys: string[];
  genreKeys: string[];
  onClose: () => void;
}) {
  const [section, setSection] = useState(sections[0] || 'drop');
  const [mood, setMood] = useState(moodKeys[0] || 'euphoric');
  const [genre, setGenre] = useState(genreKeys[0] || '');
  const [preview, setPreview] = useState<{ prompt: string; motion_prompt: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchPreview = async () => {
    setLoading(true);
    try {
      const result = await api.previewPrompt(brandName, {
        section,
        mood_quadrant: mood,
        genre,
      });
      setPreview(result);
    } catch (err) {
      setPreview({ prompt: `Error: ${err instanceof Error ? err.message : 'Unknown'}`, motion_prompt: '' });
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchPreview();
  }, [section, mood, genre]);

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <Zap className="w-5 h-5 text-[#4FC3F7]" /> Preview Prompt
          </h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-gray-700/50 flex gap-3 flex-wrap">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-400 uppercase">Section</span>
            <select className={inputCls + ' !w-auto'} value={section} onChange={(e) => setSection(e.target.value)}>
              {sections.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-400 uppercase">Mood</span>
            <select className={inputCls + ' !w-auto'} value={mood} onChange={(e) => setMood(e.target.value)}>
              {moodKeys.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-400 uppercase">Genre</span>
            <select className={inputCls + ' !w-auto'} value={genre} onChange={(e) => setGenre(e.target.value)}>
              <option value="">(none)</option>
              {genreKeys.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-400">
              <div className="animate-spin w-4 h-4 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
              Generating preview...
            </div>
          ) : preview ? (
            <>
              <div>
                <h4 className="text-xs text-gray-400 uppercase mb-2">Full Prompt</h4>
                <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-sm text-gray-200 whitespace-pre-wrap font-mono leading-relaxed">
                  {preview.prompt}
                </div>
              </div>
              {preview.motion_prompt && (
                <div>
                  <h4 className="text-xs text-gray-400 uppercase mb-2">Motion Prompt</h4>
                  <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-sm text-gray-200 whitespace-pre-wrap font-mono leading-relaxed">
                    {preview.motion_prompt}
                  </div>
                </div>
              )}
              <div className="text-xs text-gray-500">
                Prompt length: {preview.prompt.length} chars
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────
export default function BrandEditor() {
  const [brands, setBrands] = useState<string[]>([]);
  const [selectedBrand, setSelectedBrand] = useState('');
  const [brand, setBrand] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSections, setOpenSections] = useState<Set<string>>(loadOpenSections);
  const [genreSearch, setGenreSearch] = useState('');
  const [libraryGenres, setLibraryGenres] = useState<string[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const [showGenreLibrary, setShowGenreLibrary] = useState(false);
  const [librarySearch, setLibrarySearch] = useState('');
  const [copyFromModal, setCopyFromModal] = useState<string | null>(null);

  // Load genre list from Lexicon
  useEffect(() => {
    api.getGenreStats().then((stats) => {
      setLibraryGenres(stats.map((s) => s.genre).sort());
    }).catch(() => {});
  }, []);

  useEffect(() => {
    api.getBrands().then((b) => {
      setBrands(b);
      if (b.length > 0) setSelectedBrand(b[0]);
    }).catch(() => setBrands([]));
  }, []);

  useEffect(() => {
    if (!selectedBrand) return;
    api.getBrand(selectedBrand).then((data) => {
      setBrand(data);
    }).catch(() => setError('Failed to load brand'));
  }, [selectedBrand]);

  const update = useCallback((path: string[], value: any) => {
    setBrand((prev: any) => deepSet(prev, path, value));
  }, []);

  const handleSave = async () => {
    if (!brand) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveBrand(selectedBrand, brand);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(`Failed to save: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    setSaving(false);
  };

  const toggleSection = (section: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      saveOpenSections(next);
      return next;
    });
  };

  if (!brand) {
    return (
      <div className="p-6 flex flex-col items-center justify-center h-[calc(100vh-60px)]">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full mb-3" />
        <p className="text-sm text-gray-500">Loading brand data...</p>
      </div>
    );
  }

  // Extract nested data safely
  const style = brand.style || {};
  const colors = style.colors || {};
  const sections = brand.sections || {};
  const moodMods = brand.mood_modifiers || {};
  const genreMods = brand.genre_modifiers || {};
  const output = brand.output || {};
  const motifs = brand.brand_motifs || {};

  const motifKeys = Object.keys(motifs);
  const genreKeys = Object.keys(genreMods);
  const sectionKeys = Object.keys(sections);
  const moodKeys = Object.keys(moodMods);

  // Filter genres by search
  const filteredGenreKeys = genreSearch
    ? genreKeys.filter((k) => k.toLowerCase().includes(genreSearch.toLowerCase()))
    : genreKeys;

  // Genres in library not yet in brand
  const unassignedGenres = libraryGenres.filter(
    (g) => !genreKeys.some((k) => k.toLowerCase() === g.toLowerCase())
  );
  const filteredLibraryGenres = librarySearch
    ? unassignedGenres.filter((g) => g.toLowerCase().includes(librarySearch.toLowerCase()))
    : unassignedGenres;

  return (
    <div className="p-6 h-[calc(100vh-0px)] flex flex-col">
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-white">Brand Editor</h1>
          <select
            value={selectedBrand}
            onChange={(e) => setSelectedBrand(e.target.value)}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-[#4FC3F7]"
          >
            {brands.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowPreview(true)}
            className="flex items-center gap-2 px-3 py-2 bg-gray-800 border border-gray-700 text-gray-300 font-medium rounded-lg hover:bg-gray-700 transition-colors text-sm"
          >
            <Zap className="w-4 h-4" />
            Preview Prompt
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-[#4FC3F7] text-gray-900 font-medium rounded-lg hover:bg-[#81D4FA] transition-colors disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saved ? 'Saved!' : saving ? 'Saving...' : 'Save Brand'}
          </button>
        </div>
      </div>

      {/* Main layout: form + preview */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 min-h-0 overflow-hidden">
        {/* Form */}
        <div className="lg:col-span-2 overflow-y-auto space-y-3 pr-2 pb-6">

          {/* 1. Brand Identity */}
          <Accordion
            title="Brand Identity"
            icon={<Eye className="w-4 h-4 text-[#4FC3F7]" />}
            open={openSections.has('identity')}
            onToggle={() => toggleSection('identity')}
          >
            <Field label="Name">
              <TextInput
                value={brand.name || ''}
                onChange={(v) => update(['name'], v)}
              />
            </Field>
            <Field label="Description">
              <TextArea
                value={brand.description || ''}
                onChange={(v) => update(['description'], v)}
                rows={3}
              />
            </Field>
          </Accordion>

          {/* 2. Visual Style */}
          <Accordion
            title="Visual Style"
            icon={<Palette className="w-4 h-4 text-[#E040FB]" />}
            open={openSections.has('style')}
            onToggle={() => toggleSection('style')}
          >
            <Field label="Base Aesthetic">
              <TextArea
                value={style.base || ''}
                onChange={(v) => update(['style', 'base'], v)}
                rows={4}
              />
            </Field>

            <div>
              <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Color Palette</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ColorPicker label="Primary" value={colors.primary || ''} onChange={(v) => update(['style', 'colors', 'primary'], v)} />
                <ColorPicker label="Secondary" value={colors.secondary || ''} onChange={(v) => update(['style', 'colors', 'secondary'], v)} />
                <ColorPicker label="Accent" value={colors.accent || ''} onChange={(v) => update(['style', 'colors', 'accent'], v)} />
                <ColorPicker label="Warm" value={colors.warm || ''} onChange={(v) => update(['style', 'colors', 'warm'], v)} />
                <ColorPicker label="Dark" value={colors.dark || ''} onChange={(v) => update(['style', 'colors', 'dark'], v)} />
                <ColorPicker label="Eye Color" value={colors.eye_color || ''} onChange={(v) => update(['style', 'colors', 'eye_color'], v)} />
              </div>
            </div>

            <Field label="Psychedelic Colors">
              <ListOfColors
                items={colors.psychedelic || []}
                onChange={(v) => update(['style', 'colors', 'psychedelic'], v)}
              />
            </Field>

            <Field label="Recurring Elements">
              <ListOfStrings
                items={style.recurring_elements || []}
                onChange={(v) => update(['style', 'recurring_elements'], v)}
                placeholder="e.g. pixel art eyes peeking from nature"
              />
            </Field>
          </Accordion>

          {/* 3. Brand Motifs */}
          <Accordion
            title="Brand Motifs"
            icon={<Trees className="w-4 h-4 text-[#7CB342]" />}
            open={openSections.has('motifs')}
            onToggle={() => toggleSection('motifs')}
          >
            {motifKeys.map((key) => {
              const motif = motifs[key] || {};
              const prompts = motif.prompts || {};
              return (
                <div key={key} className="p-4 bg-gray-800/50 rounded-lg border border-gray-700/30 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-white capitalize">{key}</h4>
                  </div>
                  <Field label="Description">
                    <TextArea
                      value={motif.description || ''}
                      onChange={(v) => update(['brand_motifs', key, 'description'], v)}
                      rows={3}
                    />
                  </Field>
                  <div className="grid grid-cols-1 gap-3">
                    <Field label="Subtle Prompt">
                      <TextInput
                        value={prompts.subtle || ''}
                        onChange={(v) => update(['brand_motifs', key, 'prompts', 'subtle'], v)}
                      />
                    </Field>
                    <Field label="Medium Prompt">
                      <TextInput
                        value={prompts.medium || ''}
                        onChange={(v) => update(['brand_motifs', key, 'prompts', 'medium'], v)}
                      />
                    </Field>
                    <Field label="Intense Prompt">
                      <TextInput
                        value={prompts.intense || ''}
                        onChange={(v) => update(['brand_motifs', key, 'prompts', 'intense'], v)}
                      />
                    </Field>
                    {Object.keys(prompts).filter(k => !['subtle','medium','intense'].includes(k)).map(pk => (
                      <Field key={pk} label={`${pk} Prompt`}>
                        <TextInput
                          value={prompts[pk] || ''}
                          onChange={(v) => update(['brand_motifs', key, 'prompts', pk], v)}
                        />
                      </Field>
                    ))}
                  </div>
                </div>
              );
            })}
          </Accordion>

          {/* 4. Section Prompts */}
          <Accordion
            title="Section Prompts"
            icon={<Layers className="w-4 h-4 text-[#FFD54F]" />}
            open={openSections.has('sections')}
            onToggle={() => toggleSection('sections')}
          >
            {sectionKeys.map((key) => {
              const sec = sections[key] || {};
              return (
                <div key={key} className="p-4 bg-gray-800/50 rounded-lg border border-gray-700/30 space-y-3">
                  <h4 className="text-sm font-medium text-[#4FC3F7] uppercase">{key}</h4>
                  <Field label="Prompt">
                    <TextArea
                      value={sec.prompt || ''}
                      onChange={(v) => update(['sections', key, 'prompt'], v)}
                      rows={4}
                    />
                  </Field>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Field label="Motion">
                      <TextInput
                        value={sec.motion || ''}
                        onChange={(v) => update(['sections', key, 'motion'], v)}
                      />
                    </Field>
                    <Field label="Energy">
                      <TextInput
                        value={sec.energy || ''}
                        onChange={(v) => update(['sections', key, 'energy'], v)}
                      />
                    </Field>
                  </div>
                </div>
              );
            })}
          </Accordion>

          {/* 5. Mood Modifiers */}
          <Accordion
            title="Mood Modifiers"
            icon={<Music className="w-4 h-4 text-[#FF8A65]" />}
            open={openSections.has('moods')}
            onToggle={() => toggleSection('moods')}
          >
            {moodKeys.map((key) => {
              const mood = moodMods[key] || {};
              return (
                <div key={key} className="p-4 bg-gray-800/50 rounded-lg border border-gray-700/30 space-y-3">
                  <h4 className="text-sm font-medium text-white capitalize">{key}</h4>
                  <Field label="Colors">
                    <TextInput
                      value={mood.colors || ''}
                      onChange={(v) => update(['mood_modifiers', key, 'colors'], v)}
                    />
                  </Field>
                  <Field label="Atmosphere">
                    <TextInput
                      value={mood.atmosphere || ''}
                      onChange={(v) => update(['mood_modifiers', key, 'atmosphere'], v)}
                    />
                  </Field>
                  <Field label="Eyes">
                    <TextInput
                      value={mood.eyes || ''}
                      onChange={(v) => update(['mood_modifiers', key, 'eyes'], v)}
                    />
                  </Field>
                </div>
              );
            })}
          </Accordion>

          {/* 6. Genre Modifiers */}
          <Accordion
            title="Genre Modifiers"
            icon={<Sliders className="w-4 h-4 text-[#76FF03]" />}
            open={openSections.has('genres')}
            onToggle={() => toggleSection('genres')}
            badge={genreKeys.length}
          >
            {/* Search bar */}
            <div className="relative">
              <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                className={inputCls + ' !pl-9'}
                placeholder="Search genres..."
                value={genreSearch}
                onChange={(e) => setGenreSearch(e.target.value)}
              />
              {genreSearch && (
                <button
                  onClick={() => setGenreSearch('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {genreSearch && (
              <p className="text-xs text-gray-500">
                Showing {filteredGenreKeys.length} of {genreKeys.length} genres
              </p>
            )}

            {filteredGenreKeys.map((key) => {
              const genre = genreMods[key] || {};
              return (
                <div key={key} className="p-4 bg-gray-800/50 rounded-lg border border-gray-700/30 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-white">{key}</h4>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setCopyFromModal(key)}
                        className="p-1 text-gray-500 hover:text-[#4FC3F7] hover:bg-gray-700/50 rounded transition-colors"
                        title="Copy from similar genre"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => {
                          const next = { ...genreMods };
                          delete next[key];
                          update(['genre_modifiers'], next);
                        }}
                        className="p-1 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  <Field label="Extra Prompt">
                    <TextArea
                      value={genre.extra || ''}
                      onChange={(v) => update(['genre_modifiers', key, 'extra'], v)}
                      rows={2}
                    />
                  </Field>
                  <Field label="Eyes Behavior">
                    <TextInput
                      value={genre.eyes || ''}
                      onChange={(v) => update(['genre_modifiers', key, 'eyes'], v)}
                    />
                  </Field>
                  <Field label="Pixel Style">
                    <TextInput
                      value={genre.pixel_style || ''}
                      onChange={(v) => update(['genre_modifiers', key, 'pixel_style'], v)}
                    />
                  </Field>
                </div>
              );
            })}

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => {
                  const name = prompt('Genre name (e.g. "ambient"):');
                  if (!name) return;
                  update(['genre_modifiers', name], {
                    extra: '',
                    eyes: '',
                    pixel_style: '',
                  });
                }}
                className="flex items-center gap-1.5 text-sm text-[#4FC3F7] hover:text-[#81D4FA] transition-colors"
              >
                <Plus className="w-4 h-4" /> Add Genre
              </button>
              <button
                onClick={() => setShowGenreLibrary(true)}
                className="flex items-center gap-1.5 text-sm text-[#76FF03] hover:text-[#B2FF59] transition-colors"
              >
                <Music className="w-4 h-4" /> Genre Library ({unassignedGenres.length} unassigned)
              </button>
            </div>
          </Accordion>

          {/* 7. Output Settings */}
          <Accordion
            title="Output Settings"
            icon={<Monitor className="w-4 h-4 text-gray-400" />}
            open={openSections.has('output')}
            onToggle={() => toggleSection('output')}
          >
            <Field label="Resolution">
              <SelectInput
                value={output.resolution || '1920x1080'}
                onChange={(v) => update(['output', 'resolution'], v)}
                options={[
                  { label: '1920x1080 (1080p)', value: '1920x1080' },
                  { label: '3840x2160 (4K)', value: '3840x2160' },
                ]}
              />
            </Field>
            <Field label="FPS">
              <SelectInput
                value={String(output.fps || 30)}
                onChange={(v) => update(['output', 'fps'], parseInt(v))}
                options={[
                  { label: '30 fps', value: '30' },
                  { label: '60 fps', value: '60' },
                ]}
              />
            </Field>
            <Field label="Codec">
              <SelectInput
                value={output.codec || 'dxv'}
                onChange={(v) => update(['output', 'codec'], v)}
                options={[
                  { label: 'DXV', value: 'dxv' },
                  { label: 'HAP', value: 'hap' },
                ]}
              />
            </Field>
          </Accordion>
        </div>

        {/* Preview Panel */}
        <div className="overflow-y-auto bg-gray-800/60 border border-gray-700/50 rounded-xl pb-6">
          <div className="px-4 py-2 border-b border-gray-700/50 text-xs text-gray-500 flex items-center gap-2 sticky top-0 bg-gray-800/90 backdrop-blur z-10">
            <Eye className="w-3 h-3" />
            Live Preview
          </div>
          <div className="p-4 space-y-6">
            {/* Color Swatches */}
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                Color Palette
              </h3>
              <div className="flex gap-3 flex-wrap">
                {['primary', 'secondary', 'accent', 'warm', 'dark', 'eye_color'].map((key) => {
                  const val = colors[key];
                  if (!val) return null;
                  return (
                    <div key={key} className="text-center">
                      <div
                        className="w-12 h-12 rounded-lg border border-gray-700 shadow-lg"
                        style={{ backgroundColor: val }}
                      />
                      <p className="text-xs text-gray-400 mt-1">{key.replace('_', ' ')}</p>
                      <p className="text-[10px] text-gray-600 font-mono">{val}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Psychedelic colors */}
            {colors.psychedelic?.length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                  Psychedelic
                </h3>
                <div className="flex gap-2 flex-wrap">
                  {colors.psychedelic.map((c: string, i: number) => (
                    <div key={i} className="text-center">
                      <div
                        className="w-10 h-10 rounded-lg border border-gray-700 shadow-lg"
                        style={{ backgroundColor: c }}
                      />
                      <p className="text-[10px] text-gray-600 font-mono mt-1">{c}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Gradient preview */}
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                Gradient Preview
              </h3>
              <div
                className="h-16 rounded-lg border border-gray-700"
                style={{
                  background: `linear-gradient(90deg, ${colors.primary || '#000'}, ${colors.secondary || '#000'}, ${colors.accent || '#000'}, ${colors.warm || '#000'})`,
                }}
              />
            </div>

            {/* Motifs preview */}
            {motifKeys.length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                  Motifs
                </h3>
                <div className="space-y-2">
                  {motifKeys.map((key) => (
                    <div key={key} className="p-3 bg-gray-900/50 rounded-lg border border-gray-700/30">
                      <p className="text-sm text-white font-medium capitalize">{key}</p>
                      <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">
                        {motifs[key]?.description}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Genre coverage stats */}
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                Genre Coverage
              </h3>
              <div className="p-3 bg-gray-900/50 rounded-lg border border-gray-700/30 space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-400">Configured genres</span>
                  <span className="text-[#76FF03] font-medium">{genreKeys.length}</span>
                </div>
                {libraryGenres.length > 0 && (
                  <>
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-400">Lexicon genres</span>
                      <span className="text-gray-300">{libraryGenres.length}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-400">Coverage</span>
                      <span className="text-gray-300">
                        {Math.round((libraryGenres.filter((g) =>
                          genreKeys.some((k) => k.toLowerCase() === g.toLowerCase())
                        ).length / libraryGenres.length) * 100)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-700 rounded-full h-1.5 mt-1">
                      <div
                        className="bg-[#76FF03] h-1.5 rounded-full transition-all"
                        style={{
                          width: `${Math.round((libraryGenres.filter((g) =>
                            genreKeys.some((k) => k.toLowerCase() === g.toLowerCase())
                          ).length / libraryGenres.length) * 100)}%`,
                        }}
                      />
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Sections preview */}
            {sectionKeys.length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                  Sections
                </h3>
                <div className="space-y-2">
                  {sectionKeys.map((key) => (
                    <div key={key} className="p-3 bg-gray-900/50 rounded-lg border border-gray-700/30">
                      <p className="text-xs text-[#4FC3F7] font-medium uppercase mb-1">{key}</p>
                      <p className="text-xs text-gray-400 line-clamp-2">{sections[key]?.prompt}</p>
                      <div className="flex gap-4 mt-1">
                        <span className="text-[10px] text-gray-500">Motion: {sections[key]?.motion}</span>
                        <span className="text-[10px] text-gray-500">Energy: {sections[key]?.energy}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Output preview */}
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
                Output
              </h3>
              <div className="p-3 bg-gray-900/50 rounded-lg border border-gray-700/30 text-xs text-gray-400 space-y-1">
                <p>{output.resolution || '1920x1080'} @ {output.fps || 30}fps</p>
                <p>Codec: {(output.codec || 'dxv').toUpperCase()}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Preview Prompt Modal */}
      {showPreview && (
        <PreviewPromptModal
          brandName={selectedBrand}
          sections={sectionKeys}
          moodKeys={moodKeys}
          genreKeys={genreKeys}
          onClose={() => setShowPreview(false)}
        />
      )}

      {/* Genre Library Modal */}
      {showGenreLibrary && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
              <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                <Music className="w-5 h-5 text-[#76FF03]" /> Genre Library
              </h3>
              <button onClick={() => setShowGenreLibrary(false)} className="p-1 text-gray-400 hover:text-white transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-5 py-3 border-b border-gray-700/50">
              <div className="relative">
                <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  className={inputCls + ' !pl-9'}
                  placeholder="Search Lexicon genres..."
                  value={librarySearch}
                  onChange={(e) => setLibrarySearch(e.target.value)}
                />
              </div>
              <p className="text-xs text-gray-500 mt-2">
                {unassignedGenres.length} genres without visual modifiers. Click to add.
              </p>
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              {filteredLibraryGenres.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-8">
                  {librarySearch ? 'No matching genres found.' : 'All Lexicon genres have modifiers assigned.'}
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {filteredLibraryGenres.map((genre) => {
                    const similar = findSimilarGenres(genre);
                    const hasSimilar = similar.some((s) => genreKeys.some((k) => k.toLowerCase() === s.toLowerCase()));
                    return (
                      <button
                        key={genre}
                        onClick={() => {
                          // Check for similar genre to copy from
                          const sourceGenre = similar.find((s) =>
                            genreKeys.some((k) => k.toLowerCase() === s.toLowerCase())
                          );
                          if (sourceGenre) {
                            const sourceKey = genreKeys.find((k) => k.toLowerCase() === sourceGenre.toLowerCase()) || sourceGenre;
                            const source = genreMods[sourceKey] || {};
                            update(['genre_modifiers', genre], {
                              extra: source.extra || '',
                              eyes: source.eyes || '',
                              pixel_style: source.pixel_style || '',
                            });
                          } else {
                            update(['genre_modifiers', genre], {
                              extra: '',
                              eyes: '',
                              pixel_style: '',
                            });
                          }
                          setShowGenreLibrary(false);
                          setOpenSections((prev) => {
                            const next = new Set(prev);
                            next.add('genres');
                            saveOpenSections(next);
                            return next;
                          });
                        }}
                        className={`px-3 py-1.5 rounded-lg text-sm transition-colors border ${
                          hasSimilar
                            ? 'bg-[#76FF03]/10 border-[#76FF03]/30 text-[#76FF03] hover:bg-[#76FF03]/20'
                            : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white'
                        }`}
                        title={hasSimilar ? `Has similar genre: ${similar.filter((s) => genreKeys.some((k) => k.toLowerCase() === s.toLowerCase())).join(', ')}` : 'No similar genre configured'}
                      >
                        {genre}
                        {hasSimilar && <Copy className="w-3 h-3 inline ml-1.5 opacity-60" />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Copy From Similar Modal */}
      {copyFromModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md">
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
              <h3 className="text-sm font-semibold text-white">
                Copy modifiers to: <span className="text-[#4FC3F7]">{copyFromModal}</span>
              </h3>
              <button onClick={() => setCopyFromModal(null)} className="p-1 text-gray-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-2 max-h-[60vh] overflow-y-auto">
              {(() => {
                const similar = findSimilarGenres(copyFromModal);
                const available = genreKeys.filter(
                  (k) => k !== copyFromModal && (similar.includes(k.toLowerCase()) || true)
                );
                // Show similar first, then all others
                const sorted = [
                  ...available.filter((k) => similar.includes(k.toLowerCase())),
                  ...available.filter((k) => !similar.includes(k.toLowerCase())),
                ];
                if (sorted.length === 0) {
                  return <p className="text-sm text-gray-500">No other genres to copy from.</p>;
                }
                return sorted.map((sourceKey) => {
                  const source = genreMods[sourceKey] || {};
                  const isSimilar = similar.includes(sourceKey.toLowerCase());
                  return (
                    <button
                      key={sourceKey}
                      onClick={() => {
                        update(['genre_modifiers', copyFromModal], {
                          extra: source.extra || '',
                          eyes: source.eyes || '',
                          pixel_style: source.pixel_style || '',
                        });
                        setCopyFromModal(null);
                      }}
                      className={`w-full text-left p-3 rounded-lg border transition-colors ${
                        isSimilar
                          ? 'bg-[#4FC3F7]/10 border-[#4FC3F7]/30 hover:bg-[#4FC3F7]/20'
                          : 'bg-gray-800/50 border-gray-700/30 hover:bg-gray-800'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white">{sourceKey}</span>
                        {isSimilar && (
                          <span className="text-[10px] bg-[#4FC3F7]/20 text-[#4FC3F7] px-1.5 py-0.5 rounded">similar</span>
                        )}
                      </div>
                      {source.extra && (
                        <p className="text-xs text-gray-400 mt-1 line-clamp-1">{source.extra}</p>
                      )}
                    </button>
                  );
                });
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
