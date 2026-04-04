const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

function mapTrack(t: any): Track {
  return {
    id: String(t.id || ''),
    title: t.title || '',
    artist: t.artist || '',
    bpm: t.bpm || 0,
    genre: t.genre || '',
    key: t.key || '',
    energy: (t.energy || 0) / 10, // API returns 0-10, UI expects 0-1
    happiness: (t.happiness || 0) / 10,
    duration: t.duration || 0,
    status: t.has_video === true ? 'generated' : t.has_video === false ? 'pending' : 'pending',
    playlist: t.playlist || '',
    video_url: t.video_url || '',
    created_at: t.created_at || '',
  };
}

function mapModel(m: any): ModelInfo {
  // Quality: API returns "high"/"medium"/"draft" string, UI expects 1-5 number
  const qualityMap: Record<string, number> = { high: 5, medium: 3, draft: 1, low: 2 };
  const qualityNum = typeof m.quality === 'number' ? m.quality : (qualityMap[m.quality] || 3);

  // Cost: API has cost_per_second (video) or cost_per_image (image), UI expects cost_per_gen
  const costPerGen = m.cost_per_gen || m.cost_per_second || m.cost_per_image || 0;

  return {
    id: m.id || '',
    name: m.name || '',
    provider: m.provider || '',
    cost_per_gen: costPerGen,
    quality: qualityNum,
    speed: m.speed || 'medium',
    resolution: m.resolution || (m.max_duration ? `${m.max_duration}s max` : 'N/A'),
    is_default: m.is_default || false,
    tier: m.tier || undefined,
    description: m.description || undefined,
    max_duration: m.max_duration || undefined,
    supports_i2v: m.supports_i2v ?? undefined,
  };
}

export const api = {
  // Tracks — returns paginated result with total count
  getTracks: async (params?: Record<string, string>): Promise<{ tracks: Track[]; total: number }> => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    const data = await request<{ tracks: any[]; total: number }>(`/tracks${qs}`);
    return { tracks: (data.tracks || []).map(mapTrack), total: data.total || 0 };
  },
  getTrack: async (id: string): Promise<Track> => {
    const t = await request<any>(`/tracks/${id}`);
    return mapTrack(t);
  },

  // Track Colors (album art palette extraction)
  getTrackColors: async (trackId: string): Promise<{ track_id: string; palette: ColorEntry[]; error?: string }> => {
    return request<{ track_id: string; palette: ColorEntry[]; error?: string }>(`/tracks/${trackId}/colors`);
  },

  // Track Generation History
  getTrackHistory: async (trackId: string): Promise<TrackHistory> => {
    return request<TrackHistory>(`/tracks/${trackId}/history`);
  },

  // Track Metadata (rich generation metadata)
  getTrackMetadata: async (trackId: string): Promise<TrackMetadata | null> => {
    const data = await request<{ track_id: string; metadata: TrackMetadata | null; error?: string }>(`/tracks/${trackId}/metadata`);
    return data.metadata || null;
  },

  // Track Prompts
  getTrackPrompt: async (trackId: string): Promise<TrackPrompt> => {
    return request<TrackPrompt>(`/tracks/${trackId}/prompt`);
  },
  setTrackPrompt: async (trackId: string, data: { global_prompt: string; section_prompts: Record<string, string> }): Promise<TrackPrompt> => {
    return request<TrackPrompt>(`/tracks/${trackId}/prompt`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },
  clearTrackPrompt: (trackId: string) =>
    request<{ deleted: boolean }>(`/tracks/${trackId}/prompt`, { method: 'DELETE' }),

  // Genres
  getGenres: async (): Promise<string[]> => {
    const data = await request<{ genres: string[] }>('/tracks/genres');
    return data.genres || [];
  },

  // Genre exploration — detailed stats
  getGenreStats: async (): Promise<GenreStats[]> => {
    const data = await request<{ genres: GenreStats[]; total: number }>('/genres');
    return data.genres || [];
  },
  getGenreTracks: async (genre: string, params?: Record<string, string>): Promise<{ tracks: Track[]; total: number }> => {
    const qs = params ? '&' + new URLSearchParams(params).toString() : '';
    const data = await request<{ tracks: any[]; total: number }>(`/genres/${encodeURIComponent(genre)}/tracks?_=1${qs}`);
    return { tracks: (data.tracks || []).map(mapTrack), total: data.total || 0 };
  },

  // Playlists (Lexicon returns nested structure, flatten it)
  getPlaylists: async (): Promise<Playlist[]> => {
    const data = await request<{ playlists: any[] }>('/playlists');
    const flat: Playlist[] = [];
    function flatten(items: any[], depth = 0) {
      for (const p of items || []) {
        if (p.type === '2' || !p.playlists) { // actual playlist, not folder
          flat.push({ id: String(p.id), name: p.name || '', track_count: 0 });
        }
        if (p.playlists) flatten(p.playlists, depth + 1);
      }
    }
    flatten(data.playlists || []);
    return flat;
  },

  // Jobs — returns grouped by status for the queue page
  getJobs: async (): Promise<{ active: Job[]; queued: Job[]; completed: Job[] }> => {
    const data = await request<{ jobs: any[] }>('/jobs');
    const jobs: Job[] = (data.jobs || []).map((j: any) => ({
      id: String(j.id || ''),
      track_id: String(j.track_id || ''),
      track_title: j.track_title || j.title || '',
      track_artist: j.track_artist || j.artist || '',
      status: j.status || 'queued',
      progress: j.progress || 0,
      step: j.step || j.current_step || '',
      cost: j.cost || 0,
      elapsed_seconds: j.elapsed_seconds || j.elapsed || 0,
      created_at: j.created_at || '',
      completed_at: j.completed_at || undefined,
      error: j.error || undefined,
    }));
    return {
      active: jobs.filter(j => j.status === 'running' || j.status === 'active'),
      queued: jobs.filter(j => j.status === 'queued'),
      completed: jobs.filter(j => j.status === 'completed' || j.status === 'failed'),
    };
  },
  createJob: (data: { track_ids: string[] }) =>
    data.track_ids.length === 1
      ? request<any>('/jobs', { method: 'POST', body: JSON.stringify({ track_id: data.track_ids[0] }) })
      : request<any>('/jobs/bulk', { method: 'POST', body: JSON.stringify(data) }),
  cancelJob: (id: string) =>
    request<{ cancelled: boolean; job_id: string }>(`/jobs/${id}`, { method: 'DELETE' }),
  retryJob: (id: string) =>
    request<{ retried: boolean; old_job_id: string; new_job: any }>(`/jobs/${id}/retry`, { method: 'POST' }),

  // Credits
  checkCredits: () =>
    request<CreditStatus>('/system/credits'),
  clearCreditCache: () =>
    request<{ cleared: boolean }>('/system/credits/clear-cache', { method: 'POST' }),

  // Budget — map API response to page expected format
  getBudget: async (): Promise<BudgetData> => {
    const data = await request<any>('/budget/summary');
    return {
      total_spent: data.total_cost || data.total_spent || 0,
      today: data.today_cost || data.today || 0,
      this_week: data.week_cost || data.this_week || 0,
      this_month: data.month_cost || data.this_month || data.total_cost || 0,
      budget_limit: data.budget_limit || 50,
      daily_spend: (data.daily_costs || data.daily_spend || []).map((d: any) => ({
        date: d.day || d.date || '',
        amount: d.cost || d.amount || 0,
      })),
      per_model: (data.per_model || []).map((m: any) => ({
        model: m.model || m.name || '',
        amount: m.amount || m.cost || 0,
      })),
    };
  },

  // Budget — detailed per-track costs
  getBudgetPerTrack: async (): Promise<PerTrackData> => {
    return request<PerTrackData>('/budget/per-track');
  },

  // Budget — recent generations
  getBudgetRecent: async (limit = 20): Promise<RecentGeneration[]> => {
    const data = await request<{ generations: any[] }>(`/budget/recent?limit=${limit}`);
    return data.generations || [];
  },

  // Budget — bulk cost estimate
  getBulkEstimate: async (tracks: number): Promise<BulkEstimate> => {
    return request<BulkEstimate>(`/budget/estimate?tracks=${tracks}`);
  },

  // Brands — returns just the name strings for the dropdown
  getBrands: async (): Promise<string[]> => {
    const data = await request<{ brands: { name: string }[] }>('/brands');
    return (data.brands || []).map(b => b.name);
  },
  getBrand: async (name: string): Promise<any> => {
    // Returns the raw brand object from the API (parsed YAML)
    return await request<any>(`/brands/${name}`);
  },
  saveBrand: (name: string, data: any) =>
    request<any>(`/brands/${name}`, {
      method: 'PUT',
      body: JSON.stringify({ data }),
    }),
  previewPrompt: (name: string, params: { section: string; mood_quadrant: string; genre: string }) =>
    request<{ prompt: string; motion_prompt: string; section: string; mood_quadrant: string }>(
      `/brands/${name}/preview-prompt`,
      { method: 'POST', body: JSON.stringify(params) },
    ),

  // Models
  getModels: async (): Promise<ModelInfo[]> => {
    const data = await request<{ video_models?: any[]; image_models?: any[] }>('/models');
    const videoModels = (data.video_models || []).map(mapModel);
    const imageModels = (data.image_models || []).map(mapModel);
    // Mark first video model as default if none marked
    const allModels = [...videoModels, ...imageModels];
    if (allModels.length > 0 && !allModels.some(m => m.is_default)) {
      allModels[0].is_default = true;
    }
    return allModels;
  },
  setDefaultModel: (videoModel: string, imageModel?: string) => {
    const params = new URLSearchParams();
    if (videoModel) params.set('video_model', videoModel);
    if (imageModel) params.set('image_model', imageModel);
    return request<{ video_model: string; image_model: string }>(
      `/models/default?${params.toString()}`,
      { method: 'PUT' },
    );
  },

  // Settings — API returns {env: {flat keys}, db: {}} — map to nested structure
  getSettings: async (): Promise<AppSettings> => {
    const data = await request<any>('/settings');
    const env = data.env || data || {};
    return {
      api_keys: {
        openai: env.openai_api_key || env.openai_key || env.openai || '',
        replicate: env.replicate_key || env.replicate || '',
        runway: env.runway_key || env.runway || '',
        fal: env.fal_key || env.fal || '',
      },
      connections: {
        lexicon_host: env.lexicon_host || 'localhost',
        lexicon_port: env.lexicon_port || 8080,
        nas_host: env.nas_host || '',
        nas_path: env.nas_path || (env.nas_ssh_port ? `SSH port ${env.nas_ssh_port}` : '/media/visuals'),
        resolume_host: env.resolume_host || 'localhost',
        resolume_port: env.resolume_port || 7000,
      },
      log_retention_days: env.log_retention_days || 30,
    };
  },
  saveSettings: async (settings: AppSettings) => {
    // Backend expects { settings: { key: value } }
    const flat: Record<string, string> = {
      openai_api_key: settings.api_keys.openai || '',
      replicate_key: settings.api_keys.replicate || '',
      runway_key: settings.api_keys.runway || '',
      fal_key: settings.api_keys.fal || '',
      lexicon_host: settings.connections.lexicon_host,
      lexicon_port: String(settings.connections.lexicon_port),
      nas_host: settings.connections.nas_host,
      resolume_host: settings.connections.resolume_host,
      resolume_port: String(settings.connections.resolume_port),
      log_retention_days: String(settings.log_retention_days),
    };
    if ((settings as any).discord_webhook_url !== undefined) {
      flat.discord_webhook_url = (settings as any).discord_webhook_url;
    }
    return request<any>('/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings: flat }),
    });
  },
  testConnection: (type: 'lexicon' | 'nas' | 'resolume') =>
    request<Record<string, unknown>>(`/settings/test-${type}`, {
      method: 'POST',
    }),

  // Cost Protection Settings
  getCostProtection: () =>
    request<CostProtectionSettings>('/settings/cost-protection'),
  saveCostProtection: (settings: CostProtectionSettings) =>
    request<CostProtectionSettings>('/settings/cost-protection', {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),

  // Cost estimate before generation
  estimateJobCost: (trackId: string) =>
    request<CostEstimateResult>('/jobs/estimate', {
      method: 'POST',
      body: JSON.stringify({ track_id: trackId }),
    }),

  // Setup
  getSetupStatus: () =>
    request<{
      setup_complete: boolean;
      setup_dismissed?: boolean;
      sections: Record<string, { complete: boolean; fields: Record<string, any> }>;
    }>('/setup/status'),

  dismissSetup: () =>
    request<{ ok: boolean }>('/setup/dismiss', { method: 'POST' }),

  // System / Version
  getVersion: () =>
    request<{
      current: string;
      latest: string;
      update_available: boolean;
      changelog: string;
      published_at: string;
      html_url: string;
    }>('/system/version'),
  triggerUpdate: () =>
    request<{
      success: boolean;
      message: string;
      old_version: string;
      new_version: string;
    }>('/system/update', { method: 'POST' }),

  // Logs
  getLogRuns: async (): Promise<LogRun[]> => {
    const data = await request<{ runs: any[] }>('/logs/runs');
    return (data.runs || []).map((r: any) => ({
      id: String(r.id || r.run_id || ''),
      name: r.name || r.title || '',
      started_at: r.started_at || r.start_time || '',
      status: r.status || 'completed',
      entry_count: r.entry_count || r.count || 0,
    }));
  },
  getLogRun: async (runId: string): Promise<{ log_id: string; events: LogEntry[] }> => {
    const data = await request<any>(`/logs/runs/${runId}`);
    const events = (data.events || data.entries || data.logs || []).map((e: any) => ({
      timestamp: e.timestamp || e.time || '',
      level: e.level || 'info',
      message: e.message || e.msg || '',
      module: e.module || e.source || '',
    }));
    return { log_id: data.log_id || runId, events };
  },

  // Preview / Progressive Rendering
  getQualityProfiles: () =>
    request<{ profiles: QualityProfile[] }>('/preview/profiles'),
  generatePreview: (trackId: string, data?: { brand?: string; quality?: string; sections?: string[] }) =>
    request<PreviewResult>(`/preview/${trackId}/keyframes`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    }),
  approvePreview: (trackId: string, data?: { brand?: string; quality?: string; auto_approve?: boolean }) =>
    request<any>(`/preview/${trackId}/approve`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    }),
  estimateSavings: (data: { track_duration?: number; approval_rate?: number }) =>
    request<SavingsEstimate>('/preview/savings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// Convert a brand API object to a simple YAML string for the editor
function brandToYaml(data: any): string {
  const lines: string[] = [];
  lines.push(`# Brand: ${data.name || 'Untitled'}`);
  if (data.description) {
    lines.push(`# ${data.description}`);
  }
  lines.push('');

  // Colors
  if (data.colors && typeof data.colors === 'object') {
    lines.push('colors:');
    if (Array.isArray(data.colors)) {
      for (const c of data.colors) {
        if (typeof c === 'string') lines.push(`  - ${c}`);
        else if (c.name && c.value) lines.push(`  - ${c.name}: "${c.value}"`);
      }
    } else {
      for (const [k, v] of Object.entries(data.colors)) {
        lines.push(`  - ${k}: "${v}"`);
      }
    }
    lines.push('');
  }

  // Brand motifs
  if (data.brand_motifs && typeof data.brand_motifs === 'object') {
    lines.push('motifs:');
    for (const [motifName, motif] of Object.entries(data.brand_motifs as Record<string, any>)) {
      lines.push(`  - name: "${motifName}"`);
      if (motif.description) {
        lines.push(`    description: "${motif.description}"`);
      }
      if (motif.prompts && typeof motif.prompts === 'object') {
        lines.push(`    prompts:`);
        for (const [level, prompt] of Object.entries(motif.prompts)) {
          lines.push(`      ${level}: "${prompt}"`);
        }
      }
    }
    lines.push('');
  }

  // Section prompts
  if (data.section_prompts && typeof data.section_prompts === 'object') {
    lines.push('prompts:');
    for (const [section, text] of Object.entries(data.section_prompts)) {
      lines.push(`  - section: "${section}"`);
      lines.push(`    text: "${text}"`);
    }
    lines.push('');
  }

  // If nothing was generated, return a template
  if (lines.length <= 3) {
    return `# Brand: ${data.name || 'Untitled'}\n# Edit this YAML to customize visual generation\n\ncolors:\n  - primary: "#4FC3F7"\n  - secondary: "#E040FB"\n\nmotifs:\n  - name: "default"\n    description: "Default visual motif"\n\nprompts:\n  - section: "intro"\n    text: "Abstract forms emerging from darkness"\n`;
  }

  return lines.join('\n');
}

// Types
export interface Track {
  id: string;
  title: string;
  artist: string;
  bpm: number;
  genre: string;
  key: string;
  energy: number;
  happiness: number;
  duration: number;
  status: 'generated' | 'generating' | 'pending';
  playlist?: string;
  video_url?: string;
  created_at: string;
}

export interface Playlist {
  id: string;
  name: string;
  track_count: number;
}

export interface CreditStatus {
  status: 'active' | 'exhausted' | 'no_key' | 'invalid_key' | 'error';
  message: string;
  test_cost?: number;
  error?: string;
  checked_at: string;
}

export interface Job {
  id: string;
  track_id: string;
  track_title: string;
  track_artist: string;
  status: 'active' | 'queued' | 'completed' | 'failed' | 'cancelled' | 'running';
  progress: number;
  step: string;
  cost: number;
  elapsed_seconds: number;
  created_at: string;
  completed_at?: string;
  error?: string;
}

export interface JobsResponse {
  active: Job[];
  queued: Job[];
  completed: Job[];
}

export interface BudgetData {
  total_spent: number;
  today: number;
  this_week: number;
  this_month: number;
  budget_limit: number;
  daily_spend: { date: string; amount: number }[];
  per_model: { model: string; amount: number }[];
}

export interface TrackCost {
  track_name: string;
  total_calls: number;
  api_calls: number;
  cache_hits: number;
  total_cost: number;
  first_call: string;
  last_call: string;
}

export interface PerTrackData {
  tracks: TrackCost[];
  total_tracks: number;
  total_cost: number;
  avg_cost_per_track: number;
}

export interface RecentGeneration {
  id: number;
  timestamp: string;
  model: string;
  cost_usd: number;
  track_name: string;
  phrase_idx: number;
  phrase_label: string;
  style: string;
  backend: string;
  cached: number;
  quality: string;
  width: number;
  height: number;
}

export interface BulkEstimate {
  requested_tracks: number;
  avg_cost_per_track: number;
  estimated_total: number;
  based_on_tracks: number;
}

export interface BrandInfo {
  name: string;
  display_name: string;
  description: string;
}

export interface BrandData {
  name: string;
  yaml: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  cost_per_gen: number;
  quality: number;
  speed: string;
  resolution: string;
  is_default: boolean;
  tier?: number;
  description?: string;
  max_duration?: number;
  supports_i2v?: boolean;
}

export interface AppSettings {
  api_keys: {
    openai?: string;
    replicate?: string;
    runway?: string;
    fal?: string;
  };
  connections: {
    lexicon_host: string;
    lexicon_port: number;
    nas_host: string;
    nas_path: string;
    resolume_host: string;
    resolume_port: number;
  };
  log_retention_days: number;
}

export interface LogRun {
  id: string;
  name: string;
  started_at: string;
  status: 'running' | 'completed' | 'failed';
  entry_count: number;
}

export interface GenreStats {
  genre: string;
  track_count: number;
  with_visuals: number;
  visual_pct: number;
  avg_bpm: number;
  avg_energy: number;
}

export interface ColorEntry {
  hex: string;
  rgb: number[];
  name: string;
  weight: number;
}

export interface TrackPrompt {
  track_id: string;
  global_prompt: string;
  section_prompts: Record<string, string>;
  updated_at?: string;
}

export interface LogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
  module: string;
}

export interface QualityProfile {
  name: string;
  resolution: string;
  fps: number;
  video_model: string;
  video_enabled: boolean;
  cost_multiplier: number;
  description: string;
  estimated_cost_3min: number;
}

export interface PreviewSegment {
  index: number;
  label: string;
  start: number;
  end: number;
  duration: number;
  energy: number;
  genre: string;
}

export interface PreviewResult {
  track_id: string;
  track_title: string;
  quality: string;
  segments: PreviewSegment[];
  keyframe_paths: string[];
  estimated_final_cost: number;
  preview_cost: number;
  status: string;
  profile: {
    name: string;
    resolution: string;
    video_model: string;
    video_enabled: boolean;
    description: string;
  };
}

export interface TrackHistoryJob {
  id: string;
  status: string;
  brand: string;
  quality: string;
  model: string;
  cost: number;
  error: string;
  duration_secs: number | null;
  has_video: boolean;
  video_path: string;
  created_at: string;
  started_at: string;
  completed_at: string;
  segments: number;
}

export interface TrackHistoryCostDetail {
  timestamp: string;
  model: string;
  cost_usd: number;
  phrase_idx: number;
  phrase_label: string;
  style: string;
  cached: number;
  quality: string;
}

export interface TrackHistory {
  track_id: string;
  jobs: TrackHistoryJob[];
  cost_details: TrackHistoryCostDetail[];
  total_jobs: number;
  total_cost: number;
}

export interface CostProtectionSettings {
  cost_cap_per_song: number;
  cost_auto_downgrade: boolean;
  cost_confirm_threshold: number;
}

export interface CostEstimateResult {
  track_id: string;
  track_title: string;
  duration: number;
  model: string;
  total_segments: number;
  keyframe_cost: number;
  video_cost: number;
  total_estimated: number;
  budget_limit: number;
  exceeds_budget: boolean;
  suggested_model: string | null;
  suggested_cost: number | null;
  warning: string | null;
}

export interface SavingsEstimate {
  without_progressive: number;
  with_progressive: number;
  savings: number;
  savings_pct: number;
  preview_cost: number;
  final_cost: number;
  approval_rate: number;
}

export interface TrackMetadataPhraseEntry {
  start: number;
  end: number;
  duration: number;
  label: string;
  energy: number;
}

export interface TrackMetadataEnergyCurvePoint {
  time: number;
  energy: number;
}

export interface TrackMetadataSegment {
  index: number;
  label: string;
  start: number;
  end: number;
  prompt: string;
  model: string;
  cost: number;
  cached: boolean;
}

export interface TrackMetadata {
  version: string;
  generated_at: string;
  track: {
    title: string;
    artist: string;
    bpm: number;
    duration: number;
    genre: string;
    key: string;
  };
  phrase_timeline: TrackMetadataPhraseEntry[];
  energy_curve: TrackMetadataEnergyCurvePoint[];
  mood: {
    valence: number;
    arousal: number;
    quadrant: string;
    tags: string[];
  };
  segments: TrackMetadataSegment[];
  stems: {
    available: boolean;
    drums?: Record<string, number>;
    bass?: Record<string, number>;
    vocals?: Record<string, number>;
    other?: Record<string, number>;
  };
  cost_breakdown: {
    total: number;
    keyframes: number;
    video: number;
    model: string;
    quality: string;
    duration_secs: number;
  };
}
