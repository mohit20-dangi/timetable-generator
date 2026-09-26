import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Clock, CalendarRange, Building2, AlertTriangle, ChevronRight, Users } from 'lucide-react';
import { ScheduleSettings } from '../components/ScheduleSettings';
import { AcademicTermForm } from '../components/AcademicTermForm';
import { DepartmentSetup } from '../components/DepartmentSetup';
import { UserManagement } from '../components/UserManagement';

type Tab = 'schedule' | 'terms' | 'departments' | 'users';

const TABS: { id: Tab; label: string; icon: typeof Clock }[] = [
  { id: 'schedule', label: 'Bell schedule', icon: Clock },
  { id: 'terms', label: 'Term dates', icon: CalendarRange },
  { id: 'departments', label: 'Departments', icon: Building2 },
  { id: 'users', label: 'Users & roles', icon: Users },
];

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>('schedule');

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-600">Bell schedule, term dates, and department management.</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-2 border-b border-gray-200">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.id ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon size={16} /> {t.label}
            </button>
          );
        })}
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
        {tab === 'schedule' && <ScheduleSettings />}
        {tab === 'terms' && <AcademicTermForm />}
        {tab === 'departments' && <DepartmentSetup />}
        {tab === 'users' && <UserManagement />}
      </div>

      <Link
        to="/settings/danger-zone"
        className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-red-800 hover:bg-red-100 transition-colors"
      >
        <span className="flex items-center gap-3 font-medium">
          <AlertTriangle size={20} /> Danger zone - delete setup data
        </span>
        <ChevronRight size={18} />
      </Link>
    </div>
  );
}
