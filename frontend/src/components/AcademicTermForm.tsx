import { useEffect, useState } from 'react';
import { academicTermsApi } from '../api/client';
import { AcademicTerm } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Trash2 } from 'lucide-react';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const emptyForm = () => ({ id: '', name: '', start_date: '', end_date: '', working_days: [...DAYS], holidays: '' });

/** Term dates feed the .ics export's real date range and the PDF's
 * "w.e.f." / Session line (Phase 1.7) - there was previously no way to
 * create one from the UI, only to pick an existing term at generation time. */
export function AcademicTermForm() {
  const { departmentId } = useDepartment();
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [form, setForm] = useState(emptyForm());
  const [error, setError] = useState('');

  const load = () => academicTermsApi.list().then((res) => setTerms(res.data)).catch(() => setError('Could not load terms.'));

  useEffect(() => { load(); }, []);

  const toggleDay = (day: string) => {
    setForm((current) => ({
      ...current,
      working_days: current.working_days.includes(day) ? current.working_days.filter((d) => d !== day) : [...current.working_days, day],
    }));
  };

  const selectAllDays = () => setForm((current) => ({ ...current, working_days: [...DAYS] }));
  const clearAllDays = () => setForm((current) => ({ ...current, working_days: [] }));

  const create = async () => {
    setError('');
    if (!form.id || !form.name || !form.start_date || !form.end_date || !departmentId) {
      setError('Fill in an ID, name, and both dates.');
      return;
    }
    try {
      await academicTermsApi.create({
        id: form.id, department_id: departmentId, name: form.name,
        start_date: form.start_date, end_date: form.end_date,
        working_days: form.working_days,
        holidays: form.holidays.split(',').map((d) => d.trim()).filter(Boolean),
      });
      setForm(emptyForm());
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create this term.');
    }
  };

  const remove = async (id: string) => {
    await academicTermsApi.delete(id);
    load();
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Term dates</h3>
        <p className="text-sm text-gray-600">Used for the calendar export's date range and the "w.e.f." date on printed timetables.</p>
      </div>
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="rounded-lg border border-gray-200 p-4 space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <input placeholder="ID (e.g. jul_dec_2026)" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <input placeholder="Name (e.g. JUL-DEC 2026)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-lg border border-gray-300 px-3 py-2" />
          <label className="text-sm text-gray-700">Start date<input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
          <label className="text-sm text-gray-700">End date<input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm text-gray-700">Working days</label>
            <div className="flex gap-3">
              <button type="button" onClick={selectAllDays} className="text-xs text-blue-600 hover:text-blue-800">
                Select all
              </button>
              <button type="button" onClick={clearAllDays} className="text-xs text-gray-500 hover:text-gray-700">
                Clear all
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((day) => (
              <button
                key={day} type="button" onClick={() => toggleDay(day)}
                className={`px-3 py-1 text-sm rounded-full border ${form.working_days.includes(day) ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
              >
                {day}
              </button>
            ))}
          </div>
        </div>
        <input placeholder="Holidays, comma-separated dates (YYYY-MM-DD)" value={form.holidays} onChange={(e) => setForm({ ...form, holidays: e.target.value })} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        <button onClick={create} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          <Plus size={16} /> Add term
        </button>
      </div>

      <div className="space-y-2">
        {terms.map((term) => (
          <div key={term.id} className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3">
            <div>
              <p className="font-medium text-gray-900">{term.name}</p>
              <p className="text-xs text-gray-500">{term.start_date} to {term.end_date} · {term.working_days.join(', ')}</p>
            </div>
            <button onClick={() => remove(term.id)} className="p-2 text-red-600 hover:bg-red-50 rounded-lg"><Trash2 size={16} /></button>
          </div>
        ))}
        {terms.length === 0 && <p className="text-sm text-gray-500">No terms defined yet.</p>}
      </div>
    </div>
  );
}
