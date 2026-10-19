import { useState, useEffect } from 'react';
import { constraintsApi } from '../api/client';
import { ConstraintProfile, ImportanceLevel } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Save, X } from 'lucide-react';

// Every key here must be one the backend's model_builder actually reads
// (see app/solver/weights.py::SOFT_RULE_KEYS on the backend, kept in
// lockstep by a test) - there is no numeric weight anywhere in this UI.
// An admin picks how important a plain-English rule is, not a number.
// A rule with a `param` shows a number box inside its sentence
// ("Avoid more than [2] lectures in a row...") - the admin fills the blank.
// `label` stays the full sentence (with "N") for the profile summary table.
interface RuleParam { key: string; default: number; before: string; after: string }
interface RuleDefinition { key: string; label: string; description: string; param?: RuleParam }

const RULE_DEFINITIONS: RuleDefinition[] = [
  {
    key: 'minimize_student_gaps',
    label: "Don't leave free periods in the middle of a student's day",
    description: 'Keeps classes compact so students aren\'t waiting around between lectures.',
  },
  {
    key: 'balance_load_across_days',
    label: "Spread classes evenly across the week",
    description: "Don't leave one day almost empty while another is overloaded.",
  },
  {
    key: 'parallel_lab_batches',
    label: 'Run a section\'s lab batches at the same time',
    description: 'Batch A and Batch B of the same lab should be in the lab together (different rooms), not on different days.',
  },
  {
    key: 'avoid_edge_periods',
    label: 'Avoid the very first and very last period of the day',
    description: 'Prefer the middle of the day when there\'s room to.',
  },
  {
    key: 'teacher_preferred_slots',
    label: "Respect teachers' preferred timings",
    description: 'Use the availability windows each teacher marked as preferred.',
  },
  {
    key: 'fair_teacher_workload',
    label: 'Share teaching load fairly across faculty',
    description: "Don't let one teacher's week be much fuller than another's.",
  },
  {
    key: 'limit_consecutive_teaching',
    label: 'Limit back-to-back teaching for a teacher',
    description: "Gives teachers a breather between lectures. A teacher's own hard limit in their profile still applies.",
    param: { key: 'max_consecutive_teaching', default: 2, before: 'Avoid more than', after: 'lectures in a row for one teacher' },
  },
  {
    key: 'cap_teacher_daily_periods',
    label: "Cap a teacher's periods per day",
    description: "Don't pack one teacher's load into a single day.",
    param: { key: 'max_teacher_periods_per_day', default: 4, before: 'Try to keep a teacher to at most', after: 'periods in a day' },
  },
  {
    key: 'teacher_lighter_day',
    label: 'Give teachers a lighter day',
    description: 'Try to leave each teacher one day with few or no classes (at most 2 periods).',
  },
  {
    key: 'no_repeat_subject_same_day',
    label: "Don't repeat a subject on the same day",
    description: 'Labs and double periods are exceptions.',
  },
  {
    key: 'spread_subject_across_week',
    label: 'Spread each subject across the week',
    description: 'For example Mon/Wed/Fri rather than three days in a row.',
  },
  {
    key: 'heavy_subjects_early',
    label: 'Put heavy subjects earlier in the day',
    description: 'Core subjects (3 or more classes a week) go in the morning rather than the afternoon.',
  },
  {
    key: 'balanced_theory_lab_days',
    label: 'Keep days balanced between theory and labs',
    description: "Avoid a day of only labs, or only theory when there are enough labs to go around.",
  },
];

function defaultParams(): Record<string, number> {
  return Object.fromEntries(
    RULE_DEFINITIONS.filter((r) => r.param).map((r) => [r.param!.key, r.param!.default]),
  );
}

function paramsToInputs(values: Record<string, number>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, String(v)]));
}

const LEVEL_OPTIONS: { value: ImportanceLevel; label: string; hint: string }[] = [
  { value: 'must_have', label: 'Must have', hint: 'Treated as a hard rule - generation may fail if it truly can\'t be met.' },
  { value: 'very_important', label: 'Very important', hint: 'The solver works hard to satisfy this.' },
  { value: 'nice_to_have', label: 'Nice to have', hint: 'Satisfied when it doesn\'t conflict with more important things.' },
  { value: 'dont_care', label: "Don't care", hint: 'Ignored entirely.' },
];

// Only these two rules can actually be turned into a hard requirement
// (see backend app/solver/model_builder.py's must_have_rules handling) -
// "zero gaps" and "batches run together" are real hard constraints when
// promoted. The rest (fairness, preferences, day balance, edge periods)
// can't be forced to a strict guarantee without risking an otherwise-
// solvable timetable becoming infeasible, so "must have" on those stays
// a very heavy preference instead - the UI must say so honestly rather
// than promise a hard rule it can't back up.
const HARD_PROMOTABLE_KEYS = new Set(['minimize_student_gaps', 'parallel_lab_batches']);
const MUST_HAVE_SOFT_HINT = "Given the highest possible priority, but not a strict guarantee - forcing it could make an otherwise-workable timetable impossible.";

const PRESETS: { id: string; label: string; description: string; levels: Record<string, ImportanceLevel> }[] = [
  {
    id: 'balanced', label: 'Balanced', description: 'A reasonable default for most colleges.',
    levels: Object.fromEntries(RULE_DEFINITIONS.map((r) => [r.key, 'very_important' as ImportanceLevel])),
  },
  {
    id: 'student_friendly', label: 'Student-friendly', description: 'Prioritizes compact days and even spread for students.',
    levels: {
      minimize_student_gaps: 'must_have', balance_load_across_days: 'very_important',
      avoid_edge_periods: 'very_important', parallel_lab_batches: 'very_important',
      teacher_preferred_slots: 'nice_to_have', fair_teacher_workload: 'nice_to_have',
      no_repeat_subject_same_day: 'very_important', spread_subject_across_week: 'very_important',
      heavy_subjects_early: 'very_important', balanced_theory_lab_days: 'very_important',
    },
  },
  {
    id: 'teacher_friendly', label: 'Teacher-friendly', description: 'Prioritizes fair, predictable schedules for faculty.',
    levels: {
      teacher_preferred_slots: 'very_important', fair_teacher_workload: 'very_important',
      limit_consecutive_teaching: 'very_important', cap_teacher_daily_periods: 'very_important',
      teacher_lighter_day: 'very_important',
      balance_load_across_days: 'nice_to_have', minimize_student_gaps: 'nice_to_have',
      parallel_lab_batches: 'nice_to_have', avoid_edge_periods: 'nice_to_have',
    },
  },
];

function defaultLevels(): Record<string, ImportanceLevel> {
  return Object.fromEntries(RULE_DEFINITIONS.map((r) => [r.key, 'nice_to_have' as ImportanceLevel]));
}

export function ConstraintBuilder() {
  const { departmentId } = useDepartment();
  const [profiles, setProfiles] = useState<ConstraintProfile[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingProfile, setEditingProfile] = useState<ConstraintProfile | null>(null);
  const [profileId, setProfileId] = useState('');
  const [profileName, setProfileName] = useState('');
  const [levels, setLevels] = useState<Record<string, ImportanceLevel>>(defaultLevels());
  // Kept as strings while typing so the box can be cleared and retyped;
  // blank/invalid falls back to the default on save.
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(defaultParams()).map(([k, v]) => [k, String(v)])),
  );

  useEffect(() => {
    fetchProfiles();
  }, []);

  const fetchProfiles = async () => {
    try {
      const response = await constraintsApi.listProfiles();
      setProfiles(response.data);
    } catch (error) {
      console.error('Failed to fetch profiles:', error);
    }
  };

  const resetForm = () => {
    setProfileId('');
    setProfileName('');
    setLevels(defaultLevels());
    setParams(paramsToInputs(defaultParams()));
  };

  const applyPreset = (presetId: string) => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (preset) setLevels({ ...defaultLevels(), ...preset.levels });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const rule_params = Object.fromEntries(
      Object.entries(defaultParams()).map(([key, fallback]) => {
        const n = parseInt(params[key], 10);
        return [key, Number.isFinite(n) && n >= 1 ? n : fallback];
      }),
    );
    const payload = { id: profileId, name: profileName, department_id: departmentId || null, soft_constraint_weights: levels, rule_params };
    try {
      if (editingProfile) {
        await constraintsApi.updateProfile(editingProfile.id, payload);
      } else {
        await constraintsApi.createProfile(payload);
      }
      setShowForm(false);
      setEditingProfile(null);
      resetForm();
      fetchProfiles();
    } catch (error) {
      console.error('Failed to save profile:', error);
    }
  };

  const handleEdit = (profile: ConstraintProfile) => {
    setEditingProfile(profile);
    setProfileId(profile.id);
    setProfileName(profile.name);
    setLevels({ ...defaultLevels(), ...(profile.soft_constraint_weights || {}) });
    setParams(paramsToInputs({ ...defaultParams(), ...(profile.rule_params || {}) }));
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this profile?')) {
      try {
        await constraintsApi.deleteProfile(id);
        fetchProfiles();
      } catch (error) {
        console.error('Failed to delete profile:', error);
      }
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Scheduling priorities</h3>
        <button
          onClick={() => {
            setShowForm(true);
            setEditingProfile(null);
            resetForm();
          }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Profile
        </button>
      </div>

      {/* Profile Form */}
      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Profile ID</label>
                <input
                  type="text" value={profileId} onChange={(e) => setProfileId(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., default" required disabled={!!editingProfile}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Profile Name</label>
                <input
                  type="text" value={profileName} onChange={(e) => setProfileName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., Balanced" required
                />
              </div>
            </div>

            <div>
              <span className="block text-sm font-medium text-gray-700 mb-1">Start from a preset</span>
              <div className="flex flex-wrap gap-2">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.id} type="button" onClick={() => applyPreset(preset.id)}
                    title={preset.description}
                    className="px-3 py-1.5 text-sm rounded-full border border-gray-300 bg-white hover:bg-gray-100 transition-colors"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">How important is each rule?</label>
              <p className="text-sm text-gray-600 mb-3">
                No numbers to guess at - pick how important each rule is. Hard rules like room capacity
                and teacher eligibility are always respected regardless of what you choose here.
              </p>
              <div className="space-y-4">
                {RULE_DEFINITIONS.map((rule) => (
                  <div key={rule.key} className="border border-gray-200 rounded-lg p-3 bg-white">
                    {rule.param ? (
                      <p className="text-sm font-medium text-gray-900">
                        {rule.param.before}{' '}
                        <input
                          type="number" min={1} max={12} value={params[rule.param.key] ?? ''}
                          onChange={(e) => setParams({ ...params, [rule.param!.key]: e.target.value })}
                          aria-label={`${rule.param.before} ... ${rule.param.after}`}
                          className="w-14 px-2 py-0.5 mx-1 border border-gray-300 rounded text-center focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        />{' '}
                        {rule.param.after}
                      </p>
                    ) : (
                      <p className="text-sm font-medium text-gray-900">{rule.label}</p>
                    )}
                    <p className="text-xs text-gray-500 mb-2">{rule.description}</p>
                    <div className="flex flex-wrap gap-2">
                      {LEVEL_OPTIONS.map((option) => {
                        const hint = option.value === 'must_have' && !HARD_PROMOTABLE_KEYS.has(rule.key)
                          ? MUST_HAVE_SOFT_HINT
                          : option.hint;
                        return (
                        <button
                          key={option.value} type="button" title={hint}
                          onClick={() => setLevels({ ...levels, [rule.key]: option.value })}
                          className={`px-3 py-1.5 text-sm rounded-full border transition-colors ${
                            levels[rule.key] === option.value
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
                          }`}
                        >
                          {option.label}
                        </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <button type="submit" className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
                <Save size={20} />
                {editingProfile ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => { setShowForm(false); setEditingProfile(null); }}
                className="flex items-center gap-2 px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 transition-colors"
              >
                <X size={20} />
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="text-left px-4 py-2 font-medium text-gray-700">ID</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Top priorities</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((profile) => {
              const topRules = RULE_DEFINITIONS.filter(
                (r) => (profile.soft_constraint_weights?.[r.key]) === 'must_have' || (profile.soft_constraint_weights?.[r.key]) === 'very_important'
              );
              return (
                <tr key={profile.id} className="border-b border-gray-200">
                  <td className="px-4 py-2">{profile.id}</td>
                  <td className="px-4 py-2">{profile.name}</td>
                  <td className="px-4 py-2 text-sm text-gray-600">
                    {topRules.length ? topRules.map((r) => r.label).join('; ') : 'Balanced across all rules'}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => handleEdit(profile)} className="p-1 text-blue-600 hover:bg-blue-100 rounded">
                      <Save size={16} />
                    </button>
                    <button onClick={() => handleDelete(profile.id)} className="p-1 text-red-600 hover:bg-red-100 rounded">
                      <X size={16} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {profiles.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No scheduling priorities defined yet. Create one to get started.
        </div>
      )}
    </div>
  );
}
