import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Activity,
  HardDrive,
  Wifi,
  WifiOff,
  Cloud,
  Monitor,
  Music,
  Video,
  DollarSign,
  Clock,
  Play,
  Pause,
  RefreshCw,
  Hammer,
  ExternalLink,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Server,
} from 'lucide-react';
import { CreditBanner } from '../components/CreditBanner';

interface ServiceStatus {
  connected: boolean;
  status?: 'online' | 'offline' | 'unknown' | 'not_configured' | 'not_running';
  detail?: string;
  disk_free?: string;
  track_count?: number;
  error?: string;
}

interface SystemStatus {
  nas: ServiceStatus;
  lexicon: ServiceStatus;
  fal: ServiceStatus;
  resolume: ServiceStatus;
}

interface DashboardStats {
  total_tracks: number;
  tracks_with_visuals: number;
  total_cost: number;
  active_jobs: number;
  queued_jobs: number;
  paused: boolean;
}

interface RecentActivity {
  id: string;
  track_id: string;
  track_title: string;
  track_artist: string;
  status: string;
  cost: number;
  completed_at: string;
}

interface SystemHealth {
  uptime?: string;
  disk_used?: string;
  disk_total?: string;
  disk_percent?: number;
  memory_used?: string;
  memory_total?: string;
  memory_percent?: number;
}

function StatusBadge({ connected, status, label }: { connected: boolean; status?: string; label?: string }) {
  const effectiveStatus = status || (connected ? 'online' : 'offline');
  const config: Record<string, { bg: string; text: string; dot: string; label: string }> = {
    online: { bg: 'bg-green-900/30 border-green-700/30', text: 'text-green-400', dot: 'bg-green-400', label: 'Online' },
    offline: { bg: 'bg-red-900/30 border-red-700/30', text: 'text-red-400', dot: 'bg-red-400', label: 'Offline' },
    unknown: { bg: 'bg-yellow-900/30 border-yellow-700/30', text: 'text-yellow-400', dot: 'bg-yellow-400', label: 'Unknown' },
    not_configured: { bg: 'bg-gray-800/30 border-gray-600/30', text: 'text-gray-400', dot: 'bg-gray-400', label: 'Not Configured' },
    not_running: { bg: 'bg-yellow-900/30 border-yellow-700/30', text: 'text-yellow-400', dot: 'bg-yellow-400', label: 'Not Running' },
  };
  const c = config[effectiveStatus] || config.offline;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${c.bg} ${c.text} border`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {label || c.label}
    </span>
  );
}

function StatusCard({
  title,
  icon: Icon,
  connected,
  status,
  detail,
  error,
}: {
  title: string;
  icon: React.ElementType;
  connected: boolean;
  status?: string;
  detail?: string;
  error?: string;
}) {
  // Show "Credits Exhausted" label for fal.ai when detail indicates it
  const badgeLabel = detail?.toLowerCase().includes('exhausted') ? 'Credits Exhausted' : undefined;

  return (
    <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-gray-700/50 rounded-lg">
            <Icon className="w-4 h-4 text-[#4FC3F7]" />
          </div>
          <span className="text-sm font-medium text-gray-300">{title}</span>
        </div>
        <StatusBadge connected={connected} status={status} label={badgeLabel} />
      </div>
      {detail && <p className="text-xs text-gray-500">{detail}</p>}
      {error && !['not_configured', 'not_running'].includes(status || '') && (
        <p className="text-xs text-red-400 mt-1">{error}</p>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  format,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  format?: 'number' | 'currency';
}) {
  const formatted = format === 'currency' ? `$${value.toFixed(2)}` : String(value);
  return (
    <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 bg-gray-700/50 rounded-lg">
          <Icon className="w-4 h-4 text-[#4FC3F7]" />
        </div>
        <span className="text-sm text-gray-400">{label}</span>
      </div>
      <p className="text-2xl font-semibold text-white">{formatted}</p>
    </div>
  );
}

function ProgressBar({
  current,
  total,
  label,
}: {
  current: number;
  total: number;
  label: string;
}) {
  const pct = total > 0 ? (current / total) * 100 : 0;
  return (
    <div>
      <div className="flex justify-between mb-1">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs text-gray-500">
          {current} / {total} ({pct.toFixed(0)}%)
        </span>
      </div>
      <div className="w-full bg-gray-900 rounded-full h-2.5 overflow-hidden">
        <div
          className="h-2.5 rounded-full bg-[#4FC3F7] transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [activity, setActivity] = useState<RecentActivity[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [pausing, setPausing] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [dashRes, statusRes] = await Promise.allSettled([
        fetch('/api/dashboard').then((r) => r.json()),
        fetch('/api/system/status').then((r) => r.json()),
      ]);

      if (dashRes.status === 'fulfilled') {
        const d = dashRes.value;
        setStats({
          total_tracks: d.total_tracks || 0,
          tracks_with_visuals: d.tracks_with_visuals || 0,
          total_cost: d.total_cost || 0,
          active_jobs: d.active_jobs || 0,
          queued_jobs: d.queued_jobs || 0,
          paused: d.paused || false,
        });
        setActivity(d.recent_activity || []);
        setHealth(d.health || null);
      }

      if (statusRes.status === 'fulfilled') {
        setStatus(statusRes.value);
      }
    } catch {
      // Silent fail on initial load
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const togglePause = async () => {
    setPausing(true);
    try {
      const endpoint = stats?.paused ? '/api/system/resume' : '/api/system/pause';
      await fetch(endpoint, { method: 'POST' });
      await fetchAll();
    } catch {
      // ignore
    }
    setPausing(false);
  };

  const quickAction = async (action: string) => {
    try {
      if (action === 'generate') {
        await fetch('/api/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track_id: 'next' }),
        });
      } else if (action === 'rebuild') {
        await fetch('/api/resolume/rebuild', { method: 'POST' });
      }
      await fetchAll();
    } catch {
      // ignore
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">System overview and generation status</p>
        </div>
        <button
          onClick={fetchAll}
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-gray-200 bg-gray-800/60 hover:bg-gray-700/60 rounded-lg transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Credit Warning Banner */}
      <CreditBanner />

      {/* System Status Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard
          title="NAS Storage"
          icon={HardDrive}
          connected={status?.nas?.connected ?? false}
          status={status?.nas?.status}
          detail={status?.nas?.detail || (status?.nas?.disk_free ? `${status.nas.disk_free} free` : undefined)}
          error={status?.nas?.error}
        />
        <StatusCard
          title="Lexicon"
          icon={Music}
          connected={status?.lexicon?.connected ?? false}
          status={status?.lexicon?.status}
          detail={status?.lexicon?.track_count ? `${status.lexicon.track_count} tracks` : status?.lexicon?.detail}
          error={status?.lexicon?.error}
        />
        <StatusCard
          title="fal.ai"
          icon={Cloud}
          connected={status?.fal?.connected ?? false}
          status={status?.fal?.status}
          detail={status?.fal?.detail}
          error={status?.fal?.error}
        />
        <StatusCard
          title="Resolume"
          icon={Monitor}
          connected={status?.resolume?.connected ?? false}
          status={status?.resolume?.status}
          detail={status?.resolume?.detail}
          error={status?.resolume?.error}
        />
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Tracks" value={stats?.total_tracks || 0} icon={Music} />
        <StatCard label="With Visuals" value={stats?.tracks_with_visuals || 0} icon={Video} />
        <StatCard label="Total Cost" value={stats?.total_cost || 0} icon={DollarSign} format="currency" />
        <StatCard
          label="In Queue"
          value={(stats?.active_jobs || 0) + (stats?.queued_jobs || 0)}
          icon={Clock}
        />
      </div>

      {/* Visual Coverage */}
      {stats && stats.total_tracks > 0 && (
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <ProgressBar
            current={stats.tracks_with_visuals}
            total={stats.total_tracks}
            label="Visual Coverage"
          />
        </div>
      )}

      {/* Active Generation + Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active Generation */}
        <div className="lg:col-span-2 bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              Generation Queue
            </h2>
            {stats?.paused ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-900/30 text-yellow-400 border border-yellow-700/30">
                <Pause className="w-3 h-3" /> Paused
              </span>
            ) : stats?.active_jobs ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-900/30 text-blue-400 border border-blue-700/30">
                <Activity className="w-3 h-3" /> Running
              </span>
            ) : (
              <span className="text-xs text-gray-600">Idle</span>
            )}
          </div>

          {(stats?.active_jobs || 0) > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3 p-3 bg-gray-900/40 rounded-lg">
                <Loader2 className="w-5 h-5 text-[#4FC3F7] animate-spin flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-gray-200">
                    {stats?.active_jobs} active, {stats?.queued_jobs} queued
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">Processing generation pipeline...</p>
                </div>
                <button
                  onClick={() => navigate('/queue')}
                  className="text-xs text-[#4FC3F7] hover:text-[#81D4FA] flex items-center gap-1"
                >
                  View <ExternalLink className="w-3 h-3" />
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-24 text-gray-600 text-sm">
              No active generations. Use quick actions to start.
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Quick Actions
          </h2>
          <div className="space-y-2">
            <button
              onClick={togglePause}
              disabled={pausing}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                stats?.paused
                  ? 'bg-green-900/20 text-green-400 hover:bg-green-900/30 border border-green-700/30'
                  : 'bg-yellow-900/20 text-yellow-400 hover:bg-yellow-900/30 border border-yellow-700/30'
              } disabled:opacity-50`}
            >
              {pausing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : stats?.paused ? (
                <Play className="w-4 h-4" />
              ) : (
                <Pause className="w-4 h-4" />
              )}
              {stats?.paused ? 'Resume Generation' : 'Pause Generation'}
            </button>
            <button
              onClick={() => quickAction('generate')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm bg-[rgba(79,195,247,0.12)] text-[#4FC3F7] hover:bg-[rgba(79,195,247,0.2)] border border-[rgba(79,195,247,0.2)] transition-colors"
            >
              <Play className="w-4 h-4" />
              Generate Next
            </button>
            <button
              onClick={() => quickAction('rebuild')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-700/60 border border-gray-700/30 transition-colors"
            >
              <Hammer className="w-4 h-4" />
              Rebuild Show
            </button>
            <button
              onClick={() => window.open(`http://${window.location.hostname}:8080`, '_blank')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-700/60 border border-gray-700/30 transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              Open Resolume
            </button>
          </div>
        </div>
      </div>

      {/* Recent Activity + System Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Activity */}
        <div className="lg:col-span-2 bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Recent Activity
          </h2>
          {activity.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-gray-600 text-sm">
              No recent generations. Activity will appear here.
            </div>
          ) : (
            <div className="space-y-2">
              {activity.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 px-3 py-2.5 bg-gray-900/40 rounded-lg"
                >
                  <div className="flex-shrink-0">
                    {item.status === 'completed' && <CheckCircle className="w-4 h-4 text-green-400" />}
                    {item.status === 'failed' && <XCircle className="w-4 h-4 text-red-400" />}
                    {item.status === 'running' && <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />}
                    {!['completed', 'failed', 'running'].includes(item.status) && (
                      <AlertTriangle className="w-4 h-4 text-gray-500" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-200 truncate">
                      {item.track_artist ? `${item.track_artist} - ` : ''}
                      {item.track_id ? (
                        <Link
                          to={`/library/${item.track_id}`}
                          className="hover:text-[#4FC3F7] transition-colors"
                        >
                          {item.track_title}
                        </Link>
                      ) : (
                        item.track_title
                      )}
                    </p>
                    <p className="text-xs text-gray-500">{item.completed_at || ''}</p>
                  </div>
                  {item.cost > 0 && (
                    <span className="text-xs text-gray-500">${item.cost.toFixed(4)}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* System Health */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Server className="w-4 h-4 text-[#4FC3F7]" />
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
              System Health
            </h2>
          </div>
          {health ? (
            <div className="space-y-4">
              {health.uptime && (
                <div>
                  <span className="text-xs text-gray-500 block mb-1">Container Uptime</span>
                  <span className="text-sm text-gray-300">{health.uptime}</span>
                </div>
              )}
              {health.disk_percent !== undefined && (
                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-gray-500">Disk</span>
                    <span className="text-xs text-gray-500">
                      {health.disk_used} / {health.disk_total}
                    </span>
                  </div>
                  <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
                    <div
                      className={`h-2 rounded-full transition-all ${
                        health.disk_percent > 90
                          ? 'bg-red-500'
                          : health.disk_percent > 70
                          ? 'bg-yellow-500'
                          : 'bg-[#4FC3F7]'
                      }`}
                      style={{ width: `${health.disk_percent}%` }}
                    />
                  </div>
                </div>
              )}
              {health.memory_percent !== undefined && (
                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-gray-500">Memory</span>
                    <span className="text-xs text-gray-500">
                      {health.memory_used} / {health.memory_total}
                    </span>
                  </div>
                  <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
                    <div
                      className={`h-2 rounded-full transition-all ${
                        health.memory_percent > 90
                          ? 'bg-red-500'
                          : health.memory_percent > 70
                          ? 'bg-yellow-500'
                          : 'bg-[#4FC3F7]'
                      }`}
                      style={{ width: `${health.memory_percent}%` }}
                    />
                  </div>
                </div>
              )}
              {!health.uptime && health.disk_percent === undefined && health.memory_percent === undefined && (
                <p className="text-xs text-gray-600">No health data available yet.</p>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-24 text-gray-600 text-sm">
              Health data unavailable
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
