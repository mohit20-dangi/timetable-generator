import { TimeInput } from './TimeInput';
import { formatTime } from '../utils/schedule';
import { useEffect, useState } from 'react';
import { constraintRulesApi, constraintsApi, teachersApi, roomsApi, sectionsApi, subjectsApi, yearsApi } from '../api/client';
import { ConstraintRule, Teacher, Room, Section, Subject, BatchSchedulingMode, AcademicYear } from '../types';
import { sectionLabel, yearMap } from '../utils/sectionLabel';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Trash2, Edit, Save, X, ListChecks, Sparkles, Send, AlertCircle, CheckCircle } from 'lucide-react';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const RULE_TYPES: { value: string; label: string; hint: string }[] = [
  { value: 'teacher_unavailable', label: 'Teacher unavailable', hint: 'This teacher can never be scheduled in the day/time window below.' },
  { value: 'room_unavailable', label: 'Room unavailable', hint: 'This room can never be used in the day/time window below.' },
  { value: 'section_unavailable', label: 'Section unavailable', hint: "This section can't have a class in the day/time window below." },
  { value: 'teacher_preferred', label: 'Teacher prefers this window', hint: 'A soft nudge toward scheduling this teacher in the window below. How strongly is set by "Respect teachers\' preferred timings" under Scheduling priorities.' },
  { value: 'max_daily_override', label: 'Override a teacher\'s daily class cap', hint: 'Set weight to the new max classes/day for this teacher.' },
  { value: 'batch_scheduling_mode', label: 'Lab batch scheduling mode', hint: "Override how a subject's lab batches run - parallel, sequential, or merged - optionally only within a day/time window." },
  { value: 'subject_time_window', label: 'Keep a subject inside / outside a time window', hint: "e.g. 'Maths only in the morning' (leave the day blank for every day). Hard = never broken; soft = penalised per session that breaks it." },
  { value: 'max_subjects_per_day', label: 'Limit different subjects per day (section)', hint: "e.g. 'no more than 3 different subjects a day'. Pick one section, or 'All sections'." },
  { value: 'teacher_max_days_per_week', label: 'Limit the days a teacher works per week', hint: "e.g. 'Prof. Rao teaches at most 3 days a week', so the rest of the week stays free." },
  { value: 'custom', label: 'Custom (reviewed manually)', hint: "Recorded for audit, but not automatically applied - review it yourself before generating." },
];

const TARGET_TYPES = ['teacher', 'room', 'section', 'subject'] as const;

// Rule types whose priority is not the admin's to choose. The form state, the
// locked dropdown and the saved row all read from this one map, so what the
// admin sees is what gets stored. `custom` is never applied by the solver, so
// its stored "hard" is only there to satisfy the API's hard/soft enum; the UI
// says "Not applied" for it.
const FIXED_PRIORITY: Record<string, { priority: 'hard' | 'soft'; label: string }> = {
  teacher_unavailable: { priority: 'hard', label: 'Hard - never violated' },
  room_unavailable: { priority: 'hard', label: 'Hard - never violated' },
  max_daily_override: { priority: 'hard', label: 'Hard - replaces the teacher\'s daily cap' },
  teacher_preferred: { priority: 'soft', label: 'Soft - a nudge (strength is set under Scheduling priorities)' },
  custom: { priority: 'hard', label: 'Not applied - recorded only' },
};

// Admin-defined preference templates: each is locked to one target type and
// reads its parameters from `params` instead of the generic weight/window fields.
const TEMPLATE_TARGET: Record<string, (typeof TARGET_TYPES)[number]> = {
  subject_time_window: 'subject',
  max_subjects_per_day: 'section',
  teacher_max_days_per_week: 'teacher',
};
const isTemplate = (ruleType: string) => ruleType in TEMPLATE_TARGET;

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
  param_max: 3,
  param_mode: 'within' as 'within' | 'avoid',
  description: '',
});

/**
 * The direct, admin-facing editor for ConstraintRule rows - the only way
 * (besides the AI Setup Assistant on the Setup page, or the raw API) to create rules like
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
  const [years, setYears] = useState<Record<string, AcademicYear>>({});
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [allSubjects, setAllSubjects] = useState<Subject[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [error, setError] = useState('');

  const [nlText, setNlText] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);
  // Rules the AI proposed, not yet saved - nothing is written until the admin confirms.
  const [proposed, setProposed] = useState<any[] | null>(null);
  const [nlNotes, setNlNotes] = useState<{ ambiguities: string[]; unsupported: string[] }>({ ambiguities: [], unsupported: [] });
  const [nlSaving, setNlSaving] = useState(false);

  const fetchAll = async () => {
    const [rulesRes, teachersRes, roomsRes, sectionsRes, subjectsRes, yearsRes] = await Promise.all([

      constraintRulesApi.list(departmentId || undefined),
      teachersApi.list(),
      roomsApi.list(),
      sectionsApi.list(),
      subjectsApi.list(),
      yearsApi.list(),
    ]);
    setYears(yearMap(yearsRes.data));
    setRules(rulesRes.data);
    setTeachers(teachersRes.data);
    setRooms(roomsRes.data);
    setSections(sectionsRes.data);
    setSubjects(subjectsRes.data.filter((s: Subject) => s.type === 'lab'));
    setAllSubjects(subjectsRes.data);
  };

  useEffect(() => {
    fetchAll().catch(() => setError('Could not load constraint rules.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [departmentId]);

  const targetOptions = (targetType: string) => {
    if (targetType === 'teacher') return teachers.map((t) => ({ id: t.id, label: t.name }));
    if (targetType === 'room') return rooms.map((r) => ({ id: r.id, label: r.name }));
    if (targetType === 'section') {
      const options = sections.map((s) => ({ id: s.id, label: sectionLabel(s, years) }));
      return form.rule_type === 'max_subjects_per_day' ? [{ id: '*', label: 'All sections' }, ...options] : options;
    }
    // subject_time_window can target any subject; batch_scheduling_mode only lab subjects.
    return (form.rule_type === 'subject_time_window' ? allSubjects : subjects).map((s) => ({ id: s.id, label: s.name }));
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
      param_max: rule.params?.max ?? 3,
      param_mode: rule.params?.mode ?? 'within',
      description: rule.description || '',
    });
    setError('');
    setShowForm(true);
  };

  const onRuleTypeChange = (ruleType: string) => {
    setForm((prev) => {
      // These rule types can only target one kind of thing - the backend
      // enforces this too, but lock it here so the picker never lies.
      const locked = ruleType === 'batch_scheduling_mode' ? 'subject' : TEMPLATE_TARGET[ruleType];
      return {
        ...prev,
        rule_type: ruleType,
        priority: FIXED_PRIORITY[ruleType]?.priority ?? prev.priority,
        target_type: locked ?? prev.target_type,
        target_id: locked && prev.target_type !== locked ? '' : prev.target_id,
        weight: isTemplate(ruleType) && prev.weight === 0 ? 10 : prev.weight,
      };
    });
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
    const needsWindow = form.rule_type !== 'max_daily_override' && form.rule_type !== 'custom' && !isTemplate(form.rule_type);
    if (needsWindow && form.rule_type !== 'batch_scheduling_mode' && (!form.day || !form.start_time || !form.end_time)) {
      setError('Set a day, start time, and end time for this rule type.');
      return;
    }
    if (form.rule_type === 'subject_time_window' && (!form.start_time || !form.end_time || form.start_time >= form.end_time)) {
      setError('Set a start time that is before the end time (leave the day blank to apply every day).');
      return;
    }
    if ((form.rule_type === 'max_subjects_per_day' || form.rule_type === 'teacher_max_days_per_week') && form.param_max < 1) {
      setError('The limit must be at least 1.');
      return;
    }
    if (isTemplate(form.rule_type) && form.priority === 'soft' && form.weight < 1) {
      setError('A soft rule needs a weight above 0, otherwise it has no effect.');
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
      priority: FIXED_PRIORITY[form.rule_type]?.priority ?? form.priority,
      // A weight only means something for an admin-chosen soft rule, or as the
      // new cap for max_daily_override. A preferred window's strength comes from
      // the Scheduling priorities screen, not from a per-rule weight.
      weight: form.rule_type === 'max_daily_override'
        ? form.weight
        : (!FIXED_PRIORITY[form.rule_type] && form.priority === 'soft' ? form.weight : 0),
      description: form.description || null,
      source: 'manual',
    };
    if (form.rule_type === 'batch_scheduling_mode') {
      payload.batch_mode = form.batch_mode;
    }
    if (form.rule_type === 'subject_time_window') payload.params = { mode: form.param_mode };
    if (form.rule_type === 'max_subjects_per_day' || form.rule_type === 'teacher_max_days_per_week') {
      payload.params = { max: form.param_max };
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

  const handleNLSubmit = async () => {
    if (!nlText.trim()) return;
    setNlLoading(true);
    setNlError(null);
    setProposed(null);
    try {
      const response = await constraintsApi.parseNL(nlText);
      setProposed(response.data.parsed_constraints?.constraints || []);
      setNlNotes({ ambiguities: response.data.ambiguities || [], unsupported: response.data.unsupported_requests || [] });
    } catch (requestError: any) {
      setNlError(requestError.response?.data?.detail || (requestError.request
        ? 'Could not reach the server, so nothing was parsed. Check your connection and try again.'
        : `Something went wrong before the request was sent: ${requestError.message}`));
    } finally {
      setNlLoading(false);
    }
  };

  const saveProposed = async () => {
    if (!proposed?.length) return;
    if (!departmentId) {
      setNlError('Select a department first.');
      return;
    }
    setNlSaving(true);
    setNlError(null);
    try {
      const stamp = Date.now();
      await Promise.all(proposed.map((rule, i) => constraintRulesApi.create({
        ...rule, id: `rule_${stamp}_${i}`, department_id: departmentId,
      })));
      setProposed(null);
      setNlText('');
      fetchAll();
    } catch (requestError: any) {
      setNlError(requestError?.response?.data?.detail || 'Could not save these rules.');
    } finally {
      setNlSaving(false);
    }
  };

  const describeProposed = (rule: any) => {
    const target = targetOptions(rule.target_type).find((o) => o.id === rule.target_id)?.label || rule.target_id;
    const window = rule.day || rule.start_time
      ? ` - ${rule.day || 'every day'} ${formatTime(rule.start_time)}-${formatTime(rule.end_time)}`
      : '';
    return `${ruleTypeLabel(rule.rule_type)}: ${rule.target_type} ${target}${window}`;
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
    if (rule.rule_type === 'subject_time_window' && rule.start_time && rule.end_time) {
      return `${rule.day || 'Every day'} ${formatTime(rule.start_time)}-${formatTime(rule.end_time)}`;
    }
    if (!rule.day || !rule.start_time || !rule.end_time) return 'Any time';
    return `${rule.day} ${formatTime(rule.start_time)}-${formatTime(rule.end_time)}`;
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

      <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
        <h4 className="font-medium text-gray-700 mb-2 flex items-center gap-2">
          <Sparkles size={18} className="text-purple-600" />
          Describe a rule in plain English
        </h4>
        <p className="text-sm text-gray-600 mb-3">
          e.g. "Prof. Verma is unavailable on Friday from 2 to 4" or "Maths only in the morning". The AI turns it into
          structured rules for you to review - nothing is saved until you confirm.
        </p>
        <textarea
          value={nlText} onChange={(e) => setNlText(e.target.value)}
          placeholder="Describe one or more rules..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-y min-h-[80px]"
        />
        <button
          onClick={handleNLSubmit} disabled={nlLoading || !nlText.trim()}
          className="mt-2 flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
        >
          {nlLoading ? (
            <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>Thinking...</>
          ) : (
            <><Send size={18} />Parse with AI</>
          )}
        </button>

        {nlError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
            <AlertCircle size={20} className="text-red-600 mt-0.5" />
            <span className="text-sm text-red-700">{nlError}</span>
          </div>
        )}

        {proposed && (
          <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle size={20} className="text-green-600" />
              <span className="font-medium text-green-800">
                {proposed.length ? "Here's what I understood:" : "I couldn't turn that into any rules."}
              </span>
            </div>
            {proposed.length > 0 && (
              <ul className="text-sm text-gray-700 space-y-1 mb-2">
                {proposed.map((rule, i) => (
                  <li key={i} className="flex items-start justify-between gap-2">
                    <span>
                      {describeProposed(rule)}
                      <span className="text-gray-500"> ({rule.priority}{rule.priority === 'soft' && rule.weight ? `, weight ${rule.weight}` : ''})</span>
                    </span>
                    <button
                      onClick={() => setProposed(proposed.filter((_, j) => j !== i))}
                      className="p-1 text-red-500 hover:bg-red-50 rounded" aria-label="Discard this rule"
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {(nlNotes.ambiguities.length > 0 || nlNotes.unsupported.length > 0) && (
              <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-900">
                <p className="font-medium">Please double-check</p>
                {nlNotes.ambiguities.map((item) => <p key={item}>Not sure: {item}</p>)}
                {nlNotes.unsupported.map((item) => <p key={item}>Can't do as a rule: {item}</p>)}
              </div>
            )}
            {proposed.length > 0 && (
              <button
                onClick={saveProposed} disabled={nlSaving}
                className="mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors text-sm"
              >
                {nlSaving ? 'Saving...' : `Add ${proposed.length === 1 ? 'this rule' : `these ${proposed.length} rules`}`}
              </button>
            )}
          </div>
        )}
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
                  value={form.target_type} disabled={form.rule_type === 'batch_scheduling_mode' || isTemplate(form.rule_type)}
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

          {form.rule_type === 'subject_time_window' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">This subject must be...</label>
              <div className="flex flex-wrap gap-2">
                {([['within', 'Inside the window'], ['avoid', 'Outside the window']] as const).map(([value, label]) => (
                  <button
                    key={value} type="button" onClick={() => setForm({ ...form, param_mode: value })}
                    className={`px-3 py-1.5 text-sm rounded-full border transition-colors ${
                      form.param_mode === value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {(form.rule_type === 'max_subjects_per_day' || form.rule_type === 'teacher_max_days_per_week') && (
            <div className="max-w-xs">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {form.rule_type === 'max_subjects_per_day' ? 'Max different subjects per day' : 'Max working days per week'}
              </label>
              <input
                type="number" min={1} value={form.param_max}
                onChange={(e) => setForm({ ...form, param_max: e.target.value === '' ? 0 : Number(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
              />
            </div>
          )}

          {form.rule_type !== 'max_subjects_per_day' && form.rule_type !== 'teacher_max_days_per_week' && (
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
                <option value="">{form.rule_type === 'batch_scheduling_mode' ? 'No day (any period)' : form.rule_type === 'subject_time_window' ? 'Every day' : 'Select day...'}</option>
                {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <TimeInput value={form.start_time} onChange={(v) => setForm({ ...form, start_time: v })}
                className="px-3 py-2 border border-gray-300 rounded-lg"
              />
              <span className="self-center text-gray-500">to</span>
              <TimeInput value={form.end_time} onChange={(v) => setForm({ ...form, end_time: v })}
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
          )}

          {form.rule_type !== 'batch_scheduling_mode' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                {FIXED_PRIORITY[form.rule_type] ? (
                  <select
                    value={FIXED_PRIORITY[form.rule_type].priority} disabled
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100 text-gray-500"
                  >
                    <option value={FIXED_PRIORITY[form.rule_type].priority}>{FIXED_PRIORITY[form.rule_type].label}</option>
                  </select>
                ) : (
                  <select
                    value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as 'hard' | 'soft' })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white"
                  >
                    <option value="hard">Hard - never violated</option>
                    <option value="soft">Soft - nudged away from, weighted</option>
                  </select>
                )}
              </div>
              {((!FIXED_PRIORITY[form.rule_type] && form.priority === 'soft') || form.rule_type === 'max_daily_override') && (
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
                    : rule.rule_type === 'custom'
                    ? 'not applied'
                    : rule.rule_type === 'teacher_preferred'
                    ? 'soft preference'
                    : `${rule.priority === 'soft' && !FIXED_PRIORITY[rule.rule_type] ? `soft, weight ${rule.weight}` : 'hard'}${
                        rule.rule_type === 'subject_time_window' ? `, ${rule.params?.mode === 'avoid' ? 'outside' : 'inside'} window`
                        : isTemplate(rule.rule_type) ? `, max ${rule.params?.max}` : ''}`}
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
          <div className="text-center py-8 text-gray-500">No structured rules yet. Add one, or describe it in plain English above.</div>
        )}
      </div>
    </div>
  );
}
