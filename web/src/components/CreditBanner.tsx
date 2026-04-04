import { AlertTriangle, ExternalLink, RefreshCw } from 'lucide-react';
import { useCredits } from '../hooks/useCredits';

/**
 * Shows a prominent banner when fal.ai credits are exhausted or unavailable.
 * Renders nothing when credits are active.
 */
export function CreditBanner() {
  const { credits, loading, recheck, isExhausted, isNoKey, hasIssue } = useCredits();

  if (loading || !hasIssue) return null;

  const isExhaustedState = isExhausted;

  return (
    <div
      className={`flex items-center justify-between gap-3 px-4 py-3 rounded-lg border ${
        isExhaustedState
          ? 'bg-red-900/30 border-red-700/50 text-red-300'
          : 'bg-yellow-900/30 border-yellow-700/50 text-yellow-300'
      }`}
    >
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium">
            {isExhaustedState
              ? 'fal.ai credits exhausted -- generation is paused'
              : isNoKey
                ? 'No fal.ai API key configured'
                : 'fal.ai API key is invalid'}
          </p>
          {isExhaustedState && (
            <p className="text-xs mt-0.5 opacity-80">
              Top up your balance to resume generating visuals.
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {isExhaustedState && (
          <a
            href="https://fal.ai/dashboard/billing"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-800/50 hover:bg-red-700/50 rounded-lg transition-colors"
          >
            Top Up <ExternalLink className="w-3 h-3" />
          </a>
        )}
        <button
          onClick={recheck}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-800/50 hover:bg-gray-700/50 rounded-lg transition-colors"
          title="Re-check credit status"
        >
          <RefreshCw className="w-3 h-3" /> Recheck
        </button>
      </div>
    </div>
  );
}

/**
 * Compact inline credit status indicator for cards/sections.
 */
export function CreditStatusBadge() {
  const { credits, loading, isExhausted, isActive } = useCredits();

  if (loading) return null;

  if (isExhausted) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-red-900/30 text-red-400 border border-red-700/30">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
        Credits Exhausted
      </span>
    );
  }

  if (isActive) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-green-900/30 text-green-400 border border-green-700/30">
        <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
        Credits Active
      </span>
    );
  }

  return null;
}
