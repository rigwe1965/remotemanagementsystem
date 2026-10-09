import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Monitor, LayoutDashboard, Computer, Bell, Ticket,
  Users, LogOut, Shield, Terminal, Zap, FileText,
  DollarSign, Settings, Network, Package, UserCircle,
  HardDrive, Wrench, MessageSquare, ShieldAlert,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import AiAssistant from './AiAssistant';

interface NavItem { to: string; label: string; icon: React.ReactNode; roles?: string[] }

const NAV: NavItem[] = [
  { to: '/dashboard',  label: 'Overview',    icon: <LayoutDashboard size={18} /> },
  { to: '/devices',    label: 'Devices',     icon: <Computer size={18} /> },
  { to: '/alerts',     label: 'Alerts',      icon: <Bell size={18} /> },
  { to: '/tickets',    label: 'Tickets',     icon: <Ticket size={18} /> },
  { to: '/customers',  label: 'Customers',   icon: <Users size={18} />, roles: ['superadmin','admin','technician'] },
  { to: '/patches',    label: 'OS Patches',  icon: <Shield size={18} />, roles: ['superadmin','admin','technician'] },
  { to: '/scripts',    label: 'Scripts',     icon: <Terminal size={18} />, roles: ['superadmin','admin','technician'] },
  { to: '/automation', label: 'Automation',  icon: <Zap size={18} />, roles: ['superadmin','admin','technician'] },
  { to: '/reports',    label: 'Reports',     icon: <FileText size={18} />, roles: ['superadmin','admin'] },
  { to: '/billing',    label: 'Billing',     icon: <DollarSign size={18} />, roles: ['superadmin','admin'] },
  { to: '/admin',            label: 'Admin',            icon: <Settings size={18} />,   roles: ['superadmin','admin'] },
  { to: '/network',          label: 'Network Discovery', icon: <Network size={18} />,    roles: ['superadmin','admin','technician'] },
  { to: '/software-patches', label: 'Software',          icon: <Package size={18} />,    roles: ['superadmin','admin','technician'] },
  { to: '/terminal',         label: 'Remote Terminal',   icon: <Monitor size={18} />,    roles: ['superadmin','admin','technician'] },
  { to: '/disk',             label: 'Disk Management',   icon: <HardDrive size={18} />,  roles: ['superadmin','admin','technician'] },
  { to: '/maintenance',      label: 'Maintenance',        icon: <Wrench size={18} />,     roles: ['superadmin','admin','technician'] },
  { to: '/client-portal',    label: 'My Tickets',         icon: <MessageSquare size={18} />, roles: ['client'] },
  { to: '/usage-monitoring', label: 'Usage Monitoring',   icon: <ShieldAlert size={18} />, roles: ['superadmin','admin'] },
  { to: '/profile',          label: 'Profile',            icon: <UserCircle size={18} /> },
];

const ROLE_COLORS: Record<string, string> = {
  superadmin: 'bg-purple-100 text-purple-700',
  admin:      'bg-red-100 text-red-600',
  technician: 'bg-amber-100 text-amber-700',
  viewer:     'bg-green-100 text-green-700',
  client:     'bg-sky-100 text-sky-700',
};

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate('/login', { replace: true }); };

  const initials = (user?.full_name || user?.email || '?')
    .split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-60 bg-brand-800 flex flex-col shrink-0">
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 py-5 border-b border-brand-700">
          <div className="w-8 h-8 bg-linear-to-br from-brand-400 to-brand-600 rounded-lg flex items-center justify-center shadow-sm">
            <Monitor size={16} className="text-white" />
          </div>
          <span className="text-white font-bold text-base tracking-tight">RMM System</span>
        </div>

        {/* User pill */}
        <div className="px-4 py-4 border-b border-brand-700">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-linear-to-br from-brand-500 to-brand-300 flex items-center justify-center text-white text-sm font-bold shrink-0">
              {initials}
            </div>
            <div className="min-w-0">
              <p className="text-white text-sm font-medium truncate">
                {user?.full_name || user?.email}
              </p>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${ROLE_COLORS[user?.role ?? 'viewer'] ?? ''}`}>
                {user?.role?.toUpperCase()}
              </span>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          <p className="text-brand-400 text-[10px] font-bold uppercase tracking-widest px-3 mb-2">
            Navigation
          </p>
          {NAV.filter(({ roles }) => !roles || roles.includes(user?.role ?? '')).map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-500 text-white shadow-xs'
                    : 'text-brand-200 hover:bg-brand-700 hover:text-white'
                }`
              }
            >
              {icon}
              {label}
              {/* active chevron */}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-3 py-4 border-t border-brand-700 space-y-0.5">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium text-brand-300 hover:bg-brand-700 hover:text-white transition-colors"
          >
            <LogOut size={18} />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      <AiAssistant />
    </div>
  );
}
