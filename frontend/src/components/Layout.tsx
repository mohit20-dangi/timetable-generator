import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Calendar, Settings, ChevronLeft, ChevronRight, LogOut, User, Menu, ListChecks, SlidersHorizontal, Building2, LifeBuoy } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useDepartment } from '../context/DepartmentContext';
import { ROLE_LABELS, isAdmin } from '../auth/roles';

const ADMIN_NAV = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/setup', label: 'Setup', icon: ListChecks },
  { path: '/scheduling-rules', label: 'Scheduling Rules', icon: SlidersHorizontal },
  { path: '/runs', label: 'Timetables', icon: Calendar },
  { path: '/remedial', label: 'Remedial classes', icon: LifeBuoy },
  { path: '/departments', label: 'Departments', icon: Building2 },
  { path: '/settings', label: 'Settings', icon: Settings },
];
const HOD_NAV = [
  { path: '/runs', label: 'Timetables', icon: Calendar },
  { path: '/remedial', label: 'Remedial classes', icon: LifeBuoy },
];
const TEACHER_NAV = [{ path: '/my-timetable', label: 'My Timetable', icon: LayoutDashboard }];

/** Which department everything on screen belongs to. The superadmin can
 * switch; everyone else is pinned to their own department, so it's shown
 * as a label instead of a picker. */
function DepartmentSwitcher() {
  const { user } = useAuth();
  const { departments, departmentId, setDepartmentId } = useDepartment();
  const current = departments.find((d) => d.id === departmentId);
  if (!user || user.role === 'TEACHER') return null;

  return (
    <div className="px-4 py-3 border-b border-gray-200 bg-blue-50/60">
      <label htmlFor="department-switcher" className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-blue-800">
        <Building2 size={14} /> Department
      </label>
      {user.role === 'SUPERADMIN' && departments.length > 1 ? (
        <select
          id="department-switcher"
          value={departmentId}
          onChange={(e) => {
            setDepartmentId(e.target.value);
            // Every page loads its data for the active department on mount;
            // reloading is the simplest way to make all of them follow.
            window.location.reload();
          }}
          className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-2 py-1.5 text-sm font-semibold text-gray-900"
        >
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      ) : (
        <p className="mt-1 text-sm font-semibold text-gray-900 truncate">{current?.name || 'No department'}</p>
      )}
    </div>
  );
}

export function Layout() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { user, logout } = useAuth();

  const navItems = isAdmin(user?.role) ? ADMIN_NAV : user?.role === 'HOD' ? HOD_NAV : TEACHER_NAV;

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className={`fixed inset-y-0 left-0 z-50 w-64 bg-white border-r border-gray-200 transition-all duration-300 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="flex items-center justify-between h-16 px-4 border-b border-gray-200">
            <h1 className="text-xl font-bold text-blue-600 truncate">Timetable Generator</h1>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100"
            >
              {sidebarOpen ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
            </button>
          </div>

          <DepartmentSwitcher />

          {/* Navigation */}
          <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
            {navItems.map((item) => {
              const isActive = location.pathname === item.path ||
                (item.path !== '/' && location.pathname.startsWith(item.path));
              const Icon = item.icon;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                >
                  <Icon size={20} />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="p-4 border-t border-gray-200 space-y-2">
            {user && (
              <div className="flex items-center gap-2 px-1 text-xs text-gray-600">
                <User size={14} />
                <span className="truncate">{user.full_name} · {ROLE_LABELS[user.role] ?? user.role}</span>
              </div>
            )}
            <button
              onClick={logout}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            >
              <LogOut size={16} /> Log out
            </button>
            <p className="text-xs text-gray-400 text-center">v1.0.0</p>
          </div>
        </div>
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      {!sidebarOpen && (
        <>
          <button
            type="button"
            aria-label="Open navigation"
            onClick={() => setSidebarOpen(true)}
            className="fixed top-4 left-4 z-[60] p-2 rounded-lg bg-white border border-gray-300 shadow-md text-gray-700 hover:bg-gray-50"
          >
            <Menu size={20} />
          </button>
        </>
      )}

      {/* Main content */}
      <main className={`flex-1 transition-all duration-300 ${sidebarOpen ? 'lg:ml-64' : 'ml-0'}`}>
        <div className="p-6 lg:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
