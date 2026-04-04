import { useState, useEffect, useCallback } from 'react';
import { Loader2, Clock, X, CheckCircle, AlertCircle, RotateCcw, ExternalLink } from 'lucide-react';
import { api, type Job, type JobsResponse } from '../api/client';
import { useJobUpdates } from '../hooks/useWebSocket';
import { CreditBanner } from '../components/CreditBanner';

function formatElapsed(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

function JobCard({
  job,
  variant,
  onCancel,
  onRetry,
}: {
  job: Job;
  variant: 'active' | 'queued' | 'completed';
  onCancel?: (id: string) => void;
  onRetry?: (id: string) => void;
}) {
  const isCreditError = job.error?.includes('CREDITS_EXHAUSTED');
  const displayError = job.error
    ? isCreditError
      ? 'Credits exhausted -- top up at fal.ai/dashboard/billing to retry'
      : job.error.replace(/^[A-Za-z]+Error:\s*/, '')
    : null;

  return (
    <div className={`bg-gray-800/60 border rounded-lg p-4 space-y-3 ${
      job.status === 'failed' ? 'border-red-700/50' : 'border-gray-700/50'
    }`}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-white font-medium text-sm">{job.track_title}</h3>
          <p className="text-gray-400 text-xs">{job.track_artist}</p>
        </div>
        <div className="flex items-center gap-2">
          {variant === 'active' && (
            <span className="text-xs text-gray-500 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatElapsed(job.elapsed_seconds)}
            </span>
          )}
          {variant === 'queued' && onCancel && (
            <button
              onClick={() => onCancel(job.id)}
              className="p-1 text-gray-500 hover:text-red-400 transition-colors"
              title="Cancel"
            >
              <X className="w-4 h-4" />
            </button>
          )}
          {variant === 'completed' && job.status === 'completed' && (
            <CheckCircle className="w-4 h-4 text-green-400" />
          )}
          {variant === 'completed' && job.status === 'failed' && (
            <AlertCircle className="w-4 h-4 text-red-400" />
          )}
        </div>
      </div>

      {variant === 'active' && (
        <>
          <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
            <div
              className="h-2 rounded-full bg-[#4FC3F7] transition-all duration-500"
              style={{ width: `${job.progress}%` }}
            >
              <div className="h-full w-full bg-gradient-to-r from-transparent via-white/20 to-transparent animate-pulse" />
            </div>
          </div>
          <div className="flex justify-between text-xs text-gray-500">
            <span>{job.step}</span>
            <span>{job.progress}%</span>
          </div>
        </>
      )}

      {/* Error message for failed jobs */}
      {job.status === 'failed' && displayError && (
        <div className={`text-xs p-2 rounded ${
          isCreditError
            ? 'bg-red-900/30 border border-red-700/40 text-red-300'
            : 'bg-gray-900/40 text-red-400'
        }`}>
          {isCreditError && (
            <div className="flex items-center justify-between">
              <span>{displayError}</span>
              <a
                href="https://fal.ai/dashboard/billing"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-red-300 hover:text-red-200 underline ml-2 flex-shrink-0"
              >
                Top Up <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}
          {!isCreditError && <span>{displayError}</span>}
        </div>
      )}

      <div className="flex items-center justify-between">
        {job.cost > 0 && (
          <div className="text-xs text-gray-500">
            Cost: ${job.cost.toFixed(4)}
          </div>
        )}
        {job.cost === 0 && <div />}

        {/* Retry button for failed jobs */}
        {job.status === 'failed' && onRetry && (
          <button
            onClick={() => onRetry(job.id)}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-[#4FC3F7] hover:text-[#81D4FA] bg-[rgba(79,195,247,0.1)] hover:bg-[rgba(79,195,247,0.15)] rounded-md transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export default function GenerationQueue() {
  const [jobs, setJobs] = useState<JobsResponse>({
    active: [],
    queued: [],
    completed: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getJobs()
      .then(setJobs)
      .catch(() => setJobs({ active: [], queued: [], completed: [] }))
      .finally(() => setLoading(false));
  }, []);

  const handleUpdate = useCallback((data: any) => {
    if (data.type === 'job_update' && data.job) {
      setJobs((prev) => {
        const job = data.job as Job;
        const removeFrom = (arr: Job[]) => arr.filter((j) => j.id !== job.id);
        const newState = {
          active: removeFrom(prev.active),
          queued: removeFrom(prev.queued),
          completed: removeFrom(prev.completed),
        };
        if (job.status === 'active') newState.active.push(job);
        else if (job.status === 'queued') newState.queued.push(job);
        else newState.completed.unshift(job);
        return newState;
      });
    }
  }, []);

  useJobUpdates(handleUpdate);

  const handleCancel = async (id: string) => {
    setError(null);
    try {
      await api.cancelJob(id);
      setJobs((prev) => ({
        ...prev,
        queued: prev.queued.filter((j) => j.id !== id),
      }));
    } catch (err) {
      setError(`Failed to cancel job: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const handleRetry = async (id: string) => {
    setError(null);
    try {
      const result = await api.retryJob(id);
      // Refresh job list
      const fresh = await api.getJobs();
      setJobs(fresh);
    } catch (err) {
      setError(`Failed to retry job: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  // Check if any failed jobs are credit-related
  const hasCreditFailures = jobs.completed.some(
    (j) => j.status === 'failed' && j.error?.includes('CREDITS_EXHAUSTED')
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  const isEmpty = jobs.active.length === 0 && jobs.queued.length === 0 && jobs.completed.length === 0;

  return (
    <div className="p-6 space-y-8">
      <h1 className="text-2xl font-semibold text-white">Generation Queue</h1>

      {/* Credit warning banner */}
      <CreditBanner />

      {error && (
        <div className="p-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-3 text-xs">Dismiss</button>
        </div>
      )}

      {isEmpty && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Clock className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">No active jobs</p>
          <p className="text-sm mt-1">Select tracks in the Library and click "Generate Selected" to start.</p>
        </div>
      )}

      {!isEmpty && <>
      {/* Active */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Loader2 className="w-4 h-4 text-[#4FC3F7] animate-spin" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Active ({jobs.active.length})
          </h2>
        </div>
        {jobs.active.length === 0 ? (
          <p className="text-gray-600 text-sm">No active generations</p>
        ) : (
          <div className="grid gap-3">
            {jobs.active.map((job) => (
              <JobCard key={job.id} job={job} variant="active" />
            ))}
          </div>
        )}
      </section>

      {/* Queued */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4 text-yellow-500" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Queued ({jobs.queued.length})
          </h2>
        </div>
        {jobs.queued.length === 0 ? (
          <p className="text-gray-600 text-sm">Queue is empty</p>
        ) : (
          <div className="grid gap-3">
            {jobs.queued.map((job) => (
              <JobCard key={job.id} job={job} variant="queued" onCancel={handleCancel} />
            ))}
          </div>
        )}
      </section>

      {/* Completed */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Completed ({jobs.completed.length})
          </h2>
        </div>
        {jobs.completed.length === 0 ? (
          <p className="text-gray-600 text-sm">No completed jobs yet</p>
        ) : (
          <div className="grid gap-3">
            {jobs.completed.map((job) => (
              <JobCard key={job.id} job={job} variant="completed" onRetry={job.status === 'failed' ? handleRetry : undefined} />
            ))}
          </div>
        )}
      </section>
      </>}
    </div>
  );
}

const demoJobs: JobsResponse = {
  active: [
    {
      id: 'j1',
      track_id: '2',
      track_title: 'Neon Dreams',
      track_artist: 'Synthwave Kid',
      status: 'active',
      progress: 67,
      step: 'Generating keyframes (4/6)',
      cost: 0.0234,
      elapsed_seconds: 142,
      created_at: '2026-03-27T10:00:00Z',
    },
  ],
  queued: [
    {
      id: 'j2',
      track_id: '5',
      track_title: 'Electric Feel',
      track_artist: 'Voltage',
      status: 'queued',
      progress: 0,
      step: 'Waiting...',
      cost: 0,
      elapsed_seconds: 0,
      created_at: '2026-03-27T10:01:00Z',
    },
  ],
  completed: [
    {
      id: 'j3',
      track_id: '1',
      track_title: 'Midnight Run',
      track_artist: 'DJ Flash',
      status: 'completed',
      progress: 100,
      step: 'Done',
      cost: 0.0412,
      elapsed_seconds: 287,
      created_at: '2026-03-27T09:00:00Z',
      completed_at: '2026-03-27T09:05:00Z',
    },
  ],
};
