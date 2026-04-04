import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from 'recharts';
import {
  DollarSign,
  TrendingUp,
  Calendar,
  CalendarDays,
  Calculator,
  Clock,
  Hash,
  ArrowRight,
  ExternalLink,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react';
import {
  api,
  type BudgetData,
  type PerTrackData,
  type RecentGeneration,
  type BulkEstimate,
  type CreditStatus,
} from '../api/client';

const PIE_COLORS = ['#4FC3F7', '#81C784', '#FFB74D', '#E57373', '#BA68C8', '#4DD0E1'];

function SummaryCard({
  label,
  value,
  icon: Icon,
  format = 'dollar',
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  format?: 'dollar' | 'number' | 'percent';
}) {
  const formatted =
    format === 'dollar'
      ? `$${value.toFixed(2)}`
      : format === 'percent'
        ? `${(value * 100).toFixed(1)}%`
        : value.toLocaleString();

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

export default function BudgetDashboard() {
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [perTrack, setPerTrack] = useState<PerTrackData | null>(null);
  const [recent, setRecent] = useState<RecentGeneration[]>([]);
  const [bulkCount, setBulkCount] = useState(10);
  const [bulkEstimate, setBulkEstimate] = useState<BulkEstimate | null>(null);
  const [credits, setCredits] = useState<CreditStatus | null>(null);
  const [creditLoading, setCreditLoading] = useState(false);

  const recheckCredits = async () => {
    setCreditLoading(true);
    try {
      await api.clearCreditCache();
      const result = await api.checkCredits();
      setCredits(result);
    } catch {
      // ignore
    }
    setCreditLoading(false);
  };

  useEffect(() => {
    api.getBudget()
      .then(setBudget)
      .catch(() =>
        setBudget({
          total_spent: 0,
          today: 0,
          this_week: 0,
          this_month: 0,
          budget_limit: 50,
          daily_spend: [],
          per_model: [],
        }),
      );

    api.getBudgetPerTrack()
      .then(setPerTrack)
      .catch(() => setPerTrack(null));

    api.getBudgetRecent(15)
      .then(setRecent)
      .catch(() => setRecent([]));

    api.checkCredits()
      .then(setCredits)
      .catch(() => setCredits(null));
  }, []);

  // Fetch bulk estimate when count changes
  useEffect(() => {
    const timer = setTimeout(() => {
      api.getBulkEstimate(bulkCount)
        .then(setBulkEstimate)
        .catch(() => setBulkEstimate(null));
    }, 300);
    return () => clearTimeout(timer);
  }, [bulkCount]);

  if (!budget) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-[#4FC3F7] border-t-transparent rounded-full" />
      </div>
    );
  }

  const budgetPercent = budget.budget_limit > 0
    ? (budget.total_spent / budget.budget_limit) * 100
    : 0;
  const budgetColor =
    budgetPercent > 90 ? 'bg-red-500' : budgetPercent > 70 ? 'bg-yellow-500' : 'bg-[#4FC3F7]';

  const avgCostPerTrack = perTrack?.avg_cost_per_track ?? 0;

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold text-white">Budget Dashboard</h1>

      {/* fal.ai Credit Status */}
      <div className={`border rounded-xl p-5 ${
        credits?.status === 'exhausted'
          ? 'bg-red-900/20 border-red-700/50'
          : credits?.status === 'active'
            ? 'bg-gray-800/60 border-gray-700/50'
            : 'bg-yellow-900/20 border-yellow-700/50'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${
              credits?.status === 'exhausted'
                ? 'bg-red-900/40'
                : credits?.status === 'active'
                  ? 'bg-gray-700/50'
                  : 'bg-yellow-900/40'
            }`}>
              <DollarSign className={`w-5 h-5 ${
                credits?.status === 'exhausted'
                  ? 'text-red-400'
                  : credits?.status === 'active'
                    ? 'text-green-400'
                    : 'text-yellow-400'
              }`} />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-300">fal.ai Credit Status</p>
              {credits?.status === 'exhausted' ? (
                <p className="text-lg font-semibold text-red-400 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" />
                  EXHAUSTED
                </p>
              ) : credits?.status === 'active' ? (
                <p className="text-lg font-semibold text-green-400 flex items-center gap-2">
                  <CheckCircle className="w-4 h-4" />
                  Active
                </p>
              ) : credits?.status === 'no_key' ? (
                <p className="text-lg font-semibold text-yellow-400">No API Key</p>
              ) : credits ? (
                <p className="text-lg font-semibold text-yellow-400">{credits.message}</p>
              ) : (
                <p className="text-sm text-gray-500">Checking...</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a
              href="https://fal.ai/dashboard/billing"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-300 bg-gray-700/50 hover:bg-gray-600/50 rounded-lg transition-colors"
            >
              Billing <ExternalLink className="w-3 h-3" />
            </a>
            <button
              onClick={recheckCredits}
              disabled={creditLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-300 bg-gray-700/50 hover:bg-gray-600/50 rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${creditLoading ? 'animate-spin' : ''}`} />
              {creditLoading ? 'Checking...' : 'Recheck'}
            </button>
          </div>
        </div>
        {credits?.checked_at && (
          <p className="text-xs text-gray-600 mt-2">
            Last checked: {new Date(credits.checked_at).toLocaleString()}
          </p>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <SummaryCard label="Total Spent" value={budget.total_spent} icon={DollarSign} />
        <SummaryCard label="Today" value={budget.today} icon={TrendingUp} />
        <SummaryCard label="This Week" value={budget.this_week} icon={Calendar} />
        <SummaryCard label="This Month" value={budget.this_month} icon={CalendarDays} />
        <SummaryCard label="Avg / Track" value={avgCostPerTrack} icon={Hash} />
      </div>

      {/* Budget Limit Bar */}
      {budget.budget_limit > 0 && (
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <div className="flex justify-between mb-2">
            <span className="text-sm text-gray-400">Budget Usage</span>
            <span className="text-sm text-gray-300">
              ${budget.total_spent.toFixed(2)} / ${budget.budget_limit.toFixed(2)}
            </span>
          </div>
          <div className="w-full bg-gray-900 rounded-full h-4 overflow-hidden">
            <div
              className={`h-4 rounded-full ${budgetColor} transition-all duration-500`}
              style={{ width: `${Math.min(budgetPercent, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-500 mt-1">{budgetPercent.toFixed(1)}% used</p>
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Daily Spend Line Chart */}
        <div className="lg:col-span-2 bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Daily Spend
          </h2>
          {budget.daily_spend.length === 0 ? (
            <div className="flex items-center justify-center h-[260px] text-gray-600 text-sm">
              No spend data yet. Costs will appear here after generating visuals.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={budget.daily_spend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#6b7280" tick={{ fontSize: 11 }} />
                <YAxis
                  stroke="#6b7280"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => `$${v}`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                    color: '#e5e7eb',
                  }}
                  formatter={(value: any) => [`$${Number(value).toFixed(4)}`, 'Spend']}
                />
                <Line
                  type="monotone"
                  dataKey="amount"
                  stroke="#4FC3F7"
                  strokeWidth={2}
                  dot={{ fill: '#4FC3F7', r: 3 }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Per-Model Pie Chart */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Cost by Model
          </h2>
          {budget.per_model.length === 0 ? (
            <div className="flex items-center justify-center h-[200px] text-gray-600 text-sm">
              No model costs yet.
            </div>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={budget.per_model}
                    dataKey="amount"
                    nameKey="model"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    innerRadius={45}
                    paddingAngle={2}
                  >
                    {budget.per_model.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1f2937',
                      border: '1px solid #374151',
                      borderRadius: '8px',
                      color: '#e5e7eb',
                    }}
                    formatter={(value: any) => `$${Number(value).toFixed(4)}`}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1 mt-2">
                {budget.per_model.map((m, i) => (
                  <div key={m.model} className="flex items-center gap-2 text-xs text-gray-400">
                    <div
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }}
                    />
                    {m.model}: ${m.amount.toFixed(4)}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Bulk Estimate + Per-Track Cost */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bulk Cost Estimator */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Calculator className="w-4 h-4" />
            Bulk Cost Estimator
          </h2>
          <div className="space-y-4">
            <div>
              <label className="text-sm text-gray-400 block mb-2">Number of tracks to generate</label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={bulkCount}
                  onChange={(e) => setBulkCount(Math.max(1, Number(e.target.value) || 1))}
                  className="w-24 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm focus:outline-none focus:border-[#4FC3F7]"
                />
                <ArrowRight className="w-4 h-4 text-gray-600" />
                {bulkEstimate ? (
                  <div className="flex items-baseline gap-2">
                    <span className="text-xl font-semibold text-white">
                      ${bulkEstimate.estimated_total.toFixed(2)}
                    </span>
                    <span className="text-xs text-gray-500">estimated</span>
                  </div>
                ) : (
                  <span className="text-sm text-gray-600">Calculating...</span>
                )}
              </div>
            </div>
            {bulkEstimate && (
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-gray-900/50 rounded-lg p-3">
                  <p className="text-gray-500 mb-1">Avg cost / track</p>
                  <p className="text-white font-medium">${bulkEstimate.avg_cost_per_track.toFixed(4)}</p>
                </div>
                <div className="bg-gray-900/50 rounded-lg p-3">
                  <p className="text-gray-500 mb-1">Based on</p>
                  <p className="text-white font-medium">
                    {bulkEstimate.based_on_tracks > 0
                      ? `${bulkEstimate.based_on_tracks} past tracks`
                      : 'Default estimate'}
                  </p>
                </div>
              </div>
            )}
            {/* Quick presets */}
            <div className="flex gap-2">
              {[5, 10, 25, 50, 100].map((n) => (
                <button
                  key={n}
                  onClick={() => setBulkCount(n)}
                  className={`px-3 py-1.5 rounded text-xs transition-colors ${
                    bulkCount === n
                      ? 'bg-[#4FC3F7]/15 text-[#4FC3F7] border border-[#4FC3F7]/30'
                      : 'bg-gray-900/50 text-gray-500 hover:text-gray-300 border border-gray-800'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Per-Track Cost Breakdown */}
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            Cost Per Track (Top 10)
          </h2>
          {perTrack && perTrack.tracks.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                data={perTrack.tracks.slice(0, 10).map((t) => ({
                  name: t.track_name.length > 20
                    ? t.track_name.slice(0, 18) + '...'
                    : t.track_name || '(unknown)',
                  cost: t.total_cost,
                  calls: t.api_calls,
                }))}
                layout="vertical"
                margin={{ left: 10, right: 20 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis type="number" stroke="#6b7280" tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#6b7280"
                  tick={{ fontSize: 10 }}
                  width={130}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                    color: '#e5e7eb',
                  }}
                  formatter={(value: any, name: any) => [
                    name === 'cost' ? `$${Number(value).toFixed(4)}` : value,
                    name === 'cost' ? 'Cost' : 'API Calls',
                  ]}
                />
                <Bar dataKey="cost" fill="#4FC3F7" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[240px] text-gray-600 text-sm">
              No per-track data yet.
            </div>
          )}
        </div>
      </div>

      {/* Recent Generations Table */}
      <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-5">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Clock className="w-4 h-4" />
          Recent Generations
        </h2>
        {recent.length === 0 ? (
          <div className="text-center py-8 text-gray-600 text-sm">
            No generation history yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 uppercase border-b border-gray-700/50">
                  <th className="text-left py-2 pr-4">Time</th>
                  <th className="text-left py-2 pr-4">Track</th>
                  <th className="text-left py-2 pr-4">Model</th>
                  <th className="text-left py-2 pr-4">Section</th>
                  <th className="text-right py-2 pr-4">Cost</th>
                  <th className="text-center py-2">Cached</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((gen) => {
                  const ts = gen.timestamp ? new Date(gen.timestamp) : null;
                  const timeStr = ts
                    ? `${ts.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`
                    : '-';
                  return (
                    <tr key={gen.id} className="border-b border-gray-800/50 hover:bg-gray-700/20">
                      <td className="py-2 pr-4 text-gray-400 whitespace-nowrap">{timeStr}</td>
                      <td className="py-2 pr-4 text-gray-300 max-w-[200px] truncate">
                        {gen.track_name || '-'}
                      </td>
                      <td className="py-2 pr-4 text-gray-400">{gen.model || '-'}</td>
                      <td className="py-2 pr-4">
                        {gen.phrase_label ? (
                          <span className="px-2 py-0.5 rounded text-xs bg-gray-700/50 text-gray-300">
                            {gen.phrase_label}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right text-white font-medium">
                        ${gen.cost_usd.toFixed(4)}
                      </td>
                      <td className="py-2 text-center">
                        {gen.cached ? (
                          <span className="text-green-400 text-xs">cached</span>
                        ) : (
                          <span className="text-gray-600 text-xs">--</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
