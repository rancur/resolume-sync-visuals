import { useState, useEffect } from 'react';
import { Star, Check, Columns2, Cpu, Clock, Monitor, Zap } from 'lucide-react';
import { api, type ModelInfo } from '../api/client';

const TIER_LABELS: Record<number, { label: string; color: string; description: string }> = {
  1: { label: 'Tier 1 — Best Quality', color: '#FFB74D', description: 'Premium models for hero content and final renders' },
  2: { label: 'Tier 2 — Good Quality', color: '#4FC3F7', description: 'Solid quality at reasonable cost' },
  3: { label: 'Tier 3 — Budget / Fast', color: '#81C784', description: 'Cheapest options, great for drafts and previews' },
};

function QualityStars({ rating }: { rating: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={`w-3.5 h-3.5 ${
            i <= rating ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'
          }`}
        />
      ))}
    </div>
  );
}

function ModelCard({
  model,
  compareMode,
  onSetDefault,
}: {
  model: ModelInfo;
  compareMode: boolean;
  onSetDefault: (id: string) => void;
}) {
  return (
    <div
      className={`bg-gray-800/60 border rounded-xl p-5 space-y-4 transition-all ${
        model.is_default
          ? 'border-[#4FC3F7]/50 ring-1 ring-[#4FC3F7]/20'
          : 'border-gray-700/50 hover:border-gray-600'
      }`}
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-white font-medium">{model.name}</h3>
          <p className="text-xs text-gray-500">{model.provider}</p>
        </div>
        <div className="flex items-center gap-2">
          {model.supports_i2v && (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-900/30 text-green-400 border border-green-800/40">
              I2V
            </span>
          )}
          {model.is_default && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-[#4FC3F7]/15 text-[#4FC3F7] border border-[#4FC3F7]/30">
              Default
            </span>
          )}
        </div>
      </div>

      {model.description && (
        <p className="text-xs text-gray-500 leading-relaxed">{model.description}</p>
      )}

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500 flex items-center gap-1">
            <Zap className="w-3 h-3" /> Cost / gen
          </span>
          <span className="text-sm text-white font-medium">
            ${model.cost_per_gen.toFixed(4)}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500">Quality</span>
          <QualityStars rating={model.quality} />
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500 flex items-center gap-1">
            <Clock className="w-3 h-3" /> Speed
          </span>
          <span className="text-sm text-gray-300">{model.speed}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500 flex items-center gap-1">
            <Monitor className="w-3 h-3" /> Resolution
          </span>
          <span className="text-sm text-gray-300">{model.resolution}</span>
        </div>
        {model.max_duration && (
          <div className="flex justify-between items-center">
            <span className="text-xs text-gray-500">Max Duration</span>
            <span className="text-sm text-gray-300">{model.max_duration}s</span>
          </div>
        )}
      </div>

      {!model.is_default && (
        <button
          onClick={() => onSetDefault(model.id)}
          className="w-full py-2 text-sm bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <Check className="w-3.5 h-3.5" />
          Set Default
        </button>
      )}

      {compareMode && (
        <div className="pt-3 border-t border-gray-700/50">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="bg-gray-900/50 rounded p-2 text-center">
              <p className="text-gray-500">Value Score</p>
              <p className="text-white font-medium">
                {model.cost_per_gen > 0 ? ((model.quality / 5) / model.cost_per_gen).toFixed(0) : '-'}
              </p>
            </div>
            <div className="bg-gray-900/50 rounded p-2 text-center">
              <p className="text-gray-500">$/quality pt</p>
              <p className="text-white font-medium">
                ${model.quality > 0 ? (model.cost_per_gen / model.quality).toFixed(4) : '0'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ModelSelection() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [compareMode, setCompareMode] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getModels()
      .then(setModels)
      .catch(() => setModels([]))
      .finally(() => setLoading(false));
  }, []);

  const handleSetDefault = async (id: string) => {
    setError(null);
    try {
      await api.setDefaultModel(id);
      setModels((prev) =>
        prev.map((m) => ({ ...m, is_default: m.id === id }))
      );
    } catch (err) {
      setError(`Failed to set default model: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  // Group by tier
  const tiers = new Map<number, ModelInfo[]>();
  const ungrouped: ModelInfo[] = [];
  for (const m of models) {
    const tier = m.tier || 0;
    if (tier > 0) {
      if (!tiers.has(tier)) tiers.set(tier, []);
      tiers.get(tier)!.push(m);
    } else {
      ungrouped.push(m);
    }
  }
  const sortedTiers = [...tiers.entries()].sort(([a], [b]) => a - b);

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Video Models</h1>
          <p className="text-sm text-gray-500 mt-1">{models.length} models available across {tiers.size} tiers</p>
        </div>
        <button
          onClick={() => setCompareMode(!compareMode)}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-colors ${
            compareMode
              ? 'bg-[#4FC3F7]/15 text-[#4FC3F7] border border-[#4FC3F7]/30'
              : 'bg-gray-800 text-gray-400 border border-gray-700 hover:text-gray-200'
          }`}
        >
          <Columns2 className="w-4 h-4" />
          Compare Mode
        </button>
      </div>

      {models.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Cpu className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">No models available</p>
          <p className="text-sm mt-1">Check your API configuration in Settings.</p>
        </div>
      ) : (
        <div className="space-y-8">
          {sortedTiers.map(([tier, tierModels]) => {
            const info = TIER_LABELS[tier] || { label: `Tier ${tier}`, color: '#9CA3AF', description: '' };
            return (
              <div key={tier}>
                <div className="mb-4">
                  <h2 className="text-lg font-medium" style={{ color: info.color }}>
                    {info.label}
                  </h2>
                  {info.description && (
                    <p className="text-xs text-gray-500 mt-0.5">{info.description}</p>
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                  {tierModels.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
                      compareMode={compareMode}
                      onSetDefault={handleSetDefault}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          {ungrouped.length > 0 && (
            <div>
              <h2 className="text-lg font-medium text-gray-400 mb-4">Image Models</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {ungrouped.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    compareMode={compareMode}
                    onSetDefault={handleSetDefault}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
