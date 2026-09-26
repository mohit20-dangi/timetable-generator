import { useEffect, useState } from 'react';
import { constraintRulesApi, teachersApi, roomsApi, sectionsApi, subjectsApi } from '../api/client';
import { ConstraintRule, Teacher, Room, Section, Subject, BatchSchedulingMode } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Trash2, Edit, Save, X, ListChecks } from 'lucide-react';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const RULE_TYPES: { value: string; label: string; hint: string }[] = [
  { value: 'teacher_unavailable', label: 'Teacher unavailable', hint: 'This teacher can never be scheduled in the day/time window below.' },
  { value: 'room_unavailable', label: 'Room unavailable', hint: 'This room can never be used in the day/time window below.' },
  { value: 'section_unavailable', label: 'Section unavailable', hint: "This section can't have a class in the day/time window below." },
  { value: 'teacher_preferred', label: 'Teacher prefers this window', hint: 'A soft nudge toward scheduling this teacher in the window below.' },
  { value: 'max_daily_override', label: 'Override a teacher\'s daily class cap', hint: 'Set weight to the new max classes/day for this teacher.' },
  { value: 'batch_scheduling_mode', label: 'Lab batch scheduling mode', hint: "Override how a subject's lab batches run - parallel, sequential, or merged - optionally only within a day/time window." },
  { value: 'custom', label: 'Custom (reviewed manually)', hint: "Recorded for audit, but not automatically applied - review it yourself before generating." },
];

const TARGET_TYPES = ['teacher', 'room', 'section', 'subject'] as const;

const BATCH_MODES: { value: BatchSchedulingMode; label: string; hint: string }[] = [
  { value: 'independent', label: 'Independent', hint: 'No hard link between sibling batches (only a soft nudge).' },
  { value: 'parallel', label: 'Parallel', hint: 'Same time slot, separate rooms (and usually teachers).' },
  { value: 'sequential', label: 'Sequential', hint: 'Never at the same time.' },
  { value: 'merged', label: 'Merged', hint: 'Same time, same room, same teacher - one combined class.' },
];

const emptyForm = () => ({
  id: '',
  rule_type: 'teacher_unavailable',
  target_type: 'teacher' as (typeof TARGET_TYPES)[number],
  target_id: '',
  day: '' as string,
  start_time: '',
  end_time: '',
  priority: 'hard' as 'hard' | 'soft',
  weight: 0,
  batch_mode: 'parallel' as BatchSchedulingMode,
  description: '',
});

/**
 * The direct, admin-facing editor for ConstraintRule rows - the only way
 * (besides the AI assistant above, or the raw API) to create rules like
 * "Prof Sharma is never free Friday afternoon" or "merge Physics Lab's
 * batches, but only Tuesday 10-12, since that's the one slot the only
 * qualified teacher is free". ConstraintBuilder above only edits the
 * plain-language importance weights; this edits the structured, targeted
 * rules those weights can't express.
 */
export function ConstraintRulesManager() {
  const { departmentId } = useDepartment();
  const [rules, setRules] = useState<ConstraintRule[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [error, setError] = useState('');

  const fetchAll = async () => {
    const [rulesRes, teachersRes, roomsRes, sectionsRes, subjectsRes] = await Promise.all([
      constraintRulesApi.list(departmentId || undefined),
      teachersApi.list(),
      roomsApi.list(),
      sectionsApi.list(),
      subjectsApi.list(),
    ]);
    setRules(rulesRes.data);
    setTeachers(teachersRes.data);
    setRooms(roomsRes.data);
    setSections(sectionsRes.data);
    setSubjects(subjectsRes.data.filter((s: Subject) => s.type === 'lab'));
  };

  useEffect(() => {
    fetchAll().catch(() => setError('Could not load constraint rules.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [departmentId]);

  const targetOptions = (targetType: string) => {
    if (targetType === 'teacher') return teachers.map((t) => ({ id: t.id, label: t.name }));
    if (targetType === 'room') return rooms.map((r) => ({ id: r.id, label: r.name }));
    if (targetType === 'section') return sections.map((s) => ({ id: s.id, label: s.name }));
    // batch_scheduling_mode always targets a subject - only lab subjects are offered.
    return subjects.map((s) => ({ id: s.id, label: s.name }));
  };

  const resetForm = () => {
    setForm(emptyForm());
    setEditingId(null);
    setError('');
  };

  const startCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const startEdit = (rule: ConstraintRule) => {
    setEditingId(rule.id);
    setForm({
      id: rule.id,
      rule_type: rule.rule_type,
      target_type: rule.target_type as (typeof TARGET_TYPES)[number],
      target_id: rule.target_id,
      day: rule.day || '',
      start_time: (rule.start_time || '').slice(0, 5),
      end_time: (rule.end_time || '').slice(0, 5),
      priority: rule.priority,
      weight: rule.weight,
      batch_mode: (rule.batch_mode as BatchSchedulingMode) || 'parallel',
      description: rule.description || '',
    });
    setError('');
    setShowForm(true);
  };

  const onRuleTypeChange = (ruleType: string) => {
    setForm((prev) => ({
      ...prev,
      rule_type: ruleType,
      // batch_scheduling_mode can only target a subject - the backend
      // enforces this too, but lock it here so the picker never lies.
      target_type: ruleType === 'batch_scheduling_mode' ? 'subject' : prev.target_type,
      target_id: ruleType === 'batch_scheduling_mode' && prev.target_type !== 'subject' ? '' : prev.target_id,
    }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!departmentId) {
      setError('Select a department first.');
      return;
    }
    if (!form.target_id) {
      setError('Pick what this rule applies to.');
      return;
    }
    const needsWindow = form.rule_type !== 'max_daily_override' && form.rule_type !== 'custom';
    if (needsWindow && form.rule_type !== 'batch_scheduling_mode' && (!form.day || !form.start_time || !form.end_time)) {
      setError('Set a day, start time, and end time for this rule type.');
      return;
    }
    if (form.rule_type === 'batch_scheduling_mode' && (form.day || form.start_time || form.end_time)) {
      if (!form.day || !form.start_time || !form.end_time) {
        setError('A day/time window needs all three: day, start time, and end time. Leave all three blank for no window.');
        return;
      }
    }

    const payload: Record<string, unknown> = {
      id: form.id || `rule_${Date.now()}`,
      department_id: departmentId,
      rule_type: form.rule_type,
      target_type: form.target_type,
      target_id: form.target_id,
      day: form.day || null,
      start_time: form.start_time || null,
      end_time: form.end_time || null,
      priority: form.priority,
      weight: form.priority === 'soft' || form.rule_type === 'max_daily_override' ? form.weight : 0,
      description: form.description || null,
      source: 'manual',
    };
    if (form.rule_type === 'batch_scheduling_mode') {
      payload.batch_mode = form.batch_mode;
    }

    try {
      if (editingId) {
        await constraintRulesApi.update(editingId, payload);
      } else {
        await constraintRulesApi.create(payload);
      }
      setShowForm(false);
      resetForm();
      fetchAll();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'Could not save this rule.');
    }
  };

  const deleteRule = async (id: string) => {
    if (!window.confirm('Delete this rule?')) return;
    try {
      await constraintRulesApi.delete(id);
      fetchAll();
    } catch {
      setError('Could not delete this rule.');
    }
  };

  const describeTarget = (rule: ConstraintRule) => {
    const options = targetOptions(rule.target_type);
    return options.find((o) => o.id === rule.target_id)?.label || rule.target_id;
  };

  const describeWindow = (rule: ConstraintRule) => {
    if (!rule.day || !rule.start_time || !rule.end_time) return 'Any time';
    return `${rule.day} ${rule.start_time.slice(0, 5)}-${rule.end_time.slice(0, 5)}`;
  };

  const ruleTypeLabel = (value: string) => RULE_TYPES.find((r) => r.value === value)?.label || value;

  return (
    <div>
      <div className="flex items-start gap-4 mb-5">
        <div className="p-3 rounded-xl bg-indigo-50 text-indigo-700"><ListChecks size={26} /></div>
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900">Structured rules</h3>
          <p className="text-sm text-gray-600 mt-1">
            Targeted rules for a specific teacher, room, section, or subject - unavailability windows, preferences,
            daily-cap overrides, and per-subject lab batch scheduling (parallel/sequential/merged), optionally
            confined to a specific day/time.
          </p>
        </div>
        <button
          onClick={startCreate}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={18} /> Add rule
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Rule type</label>
              <select
                value={form.rule_type} onChange={(e) => onRuleTypeChange(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white"
              >
                {RULE_TYPES.map((rt) => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
              </select>
              <p className="text-xs text-gray-500 mt-1">{RULE_TYPES.find((rt) => rt.value === form.rule_type)?.hint}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Applies to</label>
              <div className="flex gap-2">
                <select
                  value={form.target_type} disabled={form.rule_type === 'batch_scheduling_mode'}
                  onChange={(e) => setForm({ ...form, target_type: e.target.value as (typeof TARGET_TYPES)[number], target_id: '' })}
                  className="px-3 py-2 border border-gray-300 rounded-lg bg-white disabled:bg-gray-100 disabled:text-gray-500"
                >
                  {TARGET_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <select
                  value={form.target_id} onChange={(e) => setForm({ ...form, target_id: e.target.value })}
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg bg-white"
                >
                  <option value="">Select...</option>
                  {targetOptions(form.target_type).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                </select>
              </div>
              {form.rule_type === 'batch_scheduling_mode' && (
                <p className="text-xs text-gray-500 mt-1">Only lab subjects are listed - this rule always targets a subject.</p>
              )}
            </div>
          </div>

          {form.rule_type === 'batch_scheduling_mode' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Batch scheduling mode</label>
              <div className="flex flex-wrap gap-2">
                {BATCH_MODES.map((m) => (
                  <button
                    key={m.value} type="button" title={m.hint}
                    onClick={() => setForm({ ...form, batch_mode: m.value })}
                    className={`px-3 py-1.5 text-sm rounded-full border transition-colors ${
                      form.batch_mode === m.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-gray-500 mt-1">{BATCH_MODES.find((m) => m.value === form.batch_mode)?.hint}</p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Day/time window
              {form.rule_type === 'batch_scheduling_mode' && (
                <span className="font-normal text-gray-500"> (optional - leave blank to apply to every period)</span>
              )}
            </label>
            <div className="flex flex-wrap gap-2">
              <select
                value={form.day} onChange={(e) => setForm({ ...form, day: e.target.value })}
                className="px-3 py-2 border border-gray-300 rounded-lg bg-white"
              >
                <option value="">{form.rule_type === 'batch_scheduling_mode' ? 'No day (any period)' : 'Select day...'}</option>
                {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <input
                type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                className="px-3 py-2 border border-gray-300 rounded-lg"
              />
              <span className="self-center text-gray-500">to</span>
              <input
                type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })}
                className="px-3 py-2 border border-gray-300 rounded-lg"
              />
            </div>
            {form.rule_type === 'batch_scheduling_mode' && (form.day || form.start_time || form.end_time) && (
              <p className="text-xs text-gray-500 mt-1">
                With a window set, this subject's lab batch sessions are confined to it - use this only when the
                window is the one slot that actually works (e.g. the only teacher qualified is free just then).
              </p>
            )}
          </div>

          {form.rule_type !== 'batch_scheduling_mode' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                <select
                  value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as 'hard' | 'soft' })}
                  disabled={form.rule_type === 'teacher_preferred' || form.rule_type === 'max_daily_override' || form.rule_type === 'custom'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white disabled:bg-gray-100 disabled:text-gray-500"
                >
                  <option value="hard">Hard - never violated</option>
                  <option value="soft">Soft - nudged away from, weighted</option>
                </select>
              </div>
              {(form.priority === 'soft' || form.rule_type === 'max_daily_override') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {form.rule_type === 'max_daily_override' ? 'New max classes/day' : 'Weight'}
                  </label>
                  <input
                    type="number" min={0} value={form.weight}
                    onChange={(e) => setForm({ ...form, weight: e.target.value === '' ? 0 : Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                  />
                </div>
              )}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
            <input
              type="text" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Why this rule exists"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            />
          </div>

          <div className="flex gap-2">
            <button type="submit" className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
              <Save size={18} /> {editingId ? 'Update' : 'Save'} rule
            </button>
            <button
              type="button" onClick={() => { setShowForm(false); resetForm(); }}
              className="flex items-center gap-2 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
            >
              <X size={18} /> Cancel
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="text-left px-4 py-2 font-medium text-gray-700">Rule</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Applies to</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Window</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Detail</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id} className="border-b border-gray-200">
                <td className="px-4 py-2 text-sm text-gray-900">
                  {ruleTypeLabel(rule.rule_type)}
                  {rule.source === 'ai_parsed' && <span className="ml-2 text-xs text-purple-600">AI</span>}
                </td>
                <td className="px-4 py-2 text-sm text-gray-700">{rule.target_type}: {describeTarget(rule)}</td>
                <td className="px-4 py-2 text-sm text-gray-600">{describeWindow(rule)}</td>
                <td className="px-4 py-2 text-sm text-gray-600">
                  {rule.rule_type === 'batch_scheduling_mode'
                    ? BATCH_MODES.find((m) => m.value === rule.batch_mode)?.label || rule.batch_mode
                    : rule.rule_type === 'max_daily_override'
                    ? `max ${rule.weight}/day`
                    : rule.priority === 'soft' ? `soft, weight ${rule.weight}` : 'hard'}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
                  <button onClick={() => startEdit(rule)} className="p-1.5 text-blue-600 hover:bg-blue-50 rounded" aria-label="Edit rule">
                    <Edit size={16} />
                  </button>
                  <button onClick={() => deleteRule(rule.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded" aria-label="Delete rule">
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rules.length === 0 && (
          <div className="text-center py-8 text-gray-500">No structured rules yet. Add one, or describe it to the AI assistant above.</div>
        )}
      </div>
    </div>
  );
}
