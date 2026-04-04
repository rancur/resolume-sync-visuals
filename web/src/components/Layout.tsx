import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  Library,
  ListOrdered,
  DollarSign,
  Palette,
  Cpu,
  Settings,
  Monitor,
  ScrollText,
  Zap,
  Music2,
  Sparkles,
  SplitSquareHorizontal,
  ListMusic,
  Radio,
  Menu,
  X,
  Clock,
} from 'lucide-react';
import { api } from '../api/client';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/library', label: 'Library', icon: Library },
  { to: '/genres', label: 'Genres', icon: Music2 },
  { to: '/queue', label: 'Queue', icon: ListOrdered },
  { to: '/budget', label: 'Budget', icon: DollarSign },
  { to: '/brand-editor', label: 'Brand Editor', icon: Palette },
  { to: '/models', label: 'Models', icon: Cpu },
  { to: '/presets', label: 'Presets', icon: Sparkles },
  { to: '/timeline', label: 'Timeline', icon: Clock },
  { to: '/compare', label: 'Compare', icon: SplitSquareHorizontal },
  { to: '/setlists', label: 'Setlists', icon: ListMusic },
  { to: '/resolume', label: 'Resolume', icon: Monitor },
  { to: '/osc', label: 'OSC Control', icon: Radio },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/logs', label: 'Logs', icon: ScrollText },
];

export default function Layout() {
  const [version, setVersion] = useState('0.1.0');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    api.getVersion()
      .then((v) => setVersion(v.current))
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-screen bg-gray-900 text-gray-200">
      {/* Mobile header */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-gray-950 border-b border-gray-800 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-[#4FC3F7]" />
          <span className="text-sm font-semibold text-white">RSV</span>
        </div>
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-2 text-gray-400 hover:text-white transition-colors"
        >
          {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed md:static z-30 top-0 left-0 h-full
          w-60 flex-shrink-0 bg-gray-950 border-r border-gray-800 flex flex-col
          transition-transform duration-200 ease-in-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
          md:translate-x-0
        `}
      >
        <div className="p-5 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <Zap className="w-6 h-6 text-[#4FC3F7]" />
            <span className="text-lg font-semibold text-white tracking-tight">
              Resolume Sync
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-1">Visual Generation Pipeline</p>
        </div>

        <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-[rgba(79,195,247,0.12)] text-[#4FC3F7] font-medium'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/60'
                }`
              }
            >
              <Icon className="w-4.5 h-4.5" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-gray-800 text-xs text-gray-600">
          v{version}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto pt-14 md:pt-0">
        <Outlet />
      </main>
    </div>
  );
}
