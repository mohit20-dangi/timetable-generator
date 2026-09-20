import { useState, useEffect } from 'react';
import { constraintsApi } from '../api/client';
import { ConstraintProfile, ImportanceLevel } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Save, X, Send, AlertCircle, CheckCircle, Sparkles } from 'lucide-react';
import { AIAssistantPanel } from './AIAssistantPanel';

// Every key here must be one the backend's model_builder actually reads
// (see app/solver/weights.py::SOFT_RULE_KEYS on the backend, kept in
// lockstep by a test) - there is no numeric weight anywhere in this UI.
// An admin picks how important a plain-English rule is, not a number.
const RULE_DEFINITIONS: { key: string; label: string; description: string }[] = [
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
];

const LEVEL_OPTIONS: { value: ImportanceLevel; label: string; hint: string }[] = [
  { value: 'must_have', label: 'Must have', hint: 'Treated as a hard rule - generation may fail if it truly can\'t be met.' },
  { value: 'very_important', label: 'Very important', hint: 'The solver works hard to satisfy this.' },
  { value: 'nice_to_have', label: 'Nice to have', hint: 'Satisfied when it doesn\'t conflict with more important things.' },
  { value: 'dont_care', label: "Don't care", hint: 'Ignored entirely.' },
];

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
    },
  },
  {
    id: 'teacher_friendly', label: 'Teacher-friendly', description: 'Prioritizes fair, predictable schedules for faculty.',
    levels: {
      teacher_preferred_slots: 'very_important', fair_teacher_workload: 'very_important',
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

  const [nlText, setNlText] = useState('');
  const [nlResult, setNlResult] = useState<any>(null);
  const [nlLoading, setNlLoading] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);

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
  };

  const applyPreset = (presetId: string) => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (preset) setLevels({ ...defaultLevels(), ...preset.levels });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload = { id: profileId, name: profileName, department_id: departmentId || null, soft_constraint_weights: levels };
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

  const handleNLSubmit = async () => {
    if (!nlText.trim()) return;
    setNlLoading(true);
    setNlError(null);
    setNlResult(null);
    try {
      const response = await constraintsApi.parseNL(nlText);
      setNlResult(response.data.parsed_constraints);
    } catch (error: any) {
      setNlError(error.response?.data?.detail || 'Failed to parse constraints. If no AI key is configured, use the form below instead.');
    } finally {
      setNlLoading(false);
    }
  };

  const handleNLImport = () => {
    if (!nlResult) return;
    setProfileId(`profile_${Date.now()}`);
    setProfileName('Imported from AI');
    setLevels({ ...defaultLevels(), ...(nlResult.soft_constraint_weights || {}) });
    setShowForm(true);
    setNlResult(null);
    setNlText('');
  };

  const describeLevel = (weights: Record<string, any>, key: string) => {
    const level = weights?.[key] as ImportanceLevel | undefined;
    return LEVEL_OPTIONS.find((l) => l.value === level)?.label || 'Nice to have';
  };

  return (
    <div>
      {departmentId && (
        <div className="mb-6">
          <AIAssistantPanel departmentId={departmentId} />
        </div>
      )}

      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Constraint Profiles</h3>
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

      {/* AI-assisted natural language parsing */}
      <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
        <h4 className="font-medium text-gray-700 mb-2 flex items-center gap-2">
          <Sparkles size={18} className="text-purple-600" />
          Describe your priorities in plain English
        </h4>
        <p className="text-sm text-gray-600 mb-3">
          e.g. "Keep student gaps to a minimum, and make sure lab batches always run together."
        </p>
        <textarea
          value={nlText}
          onChange={(e) => setNlText(e.target.value)}
          placeholder="Describe your scheduling priorities..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-y min-h-[80px]"
        />
        <div className="flex gap-2 mt-2">
          <button
            onClick={handleNLSubmit}
            disabled={nlLoading || !nlText.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {nlLoading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                Thinking...
              </>
            ) : (
              <>
                <Send size={20} />
                Parse with AI
              </>
            )}
          </button>
        </div>

        {nlError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
            <AlertCircle size={20} className="text-red-600 mt-0.5" />
            <span className="text-sm text-red-700">{nlError}</span>
          </div>
        )}

        {nlResult && (
          <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle size={20} className="text-green-600" />
              <span className="font-medium text-green-800">Here's what I understood:</span>
            </div>
            <ul className="text-sm text-gray-700 space-y-1 mb-2">
              {RULE_DEFINITIONS.map((rule) => (
                <li key={rule.key}>
                  <span className="font-medium">{rule.label}:</span> {describeLevel(nlResult.soft_constraint_weights || {}, rule.key)}
                </li>
              ))}
            </ul>
            {(nlResult.ambiguities?.length > 0 || nlResult.unsupported_requests?.length > 0) && (
              <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-900">
                <p className="font-medium">Please double-check before saving</p>
                {nlResult.ambiguities?.map((item: string) => <p key={item}>Not sure: {item}</p>)}
                {nlResult.unsupported_requests?.map((item: string) => <p key={item}>Can't do yet: {item}</p>)}
              </div>
            )}
            <button
              onClick={handleNLImport}
              className="mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
            >
              Use this as a starting point
            </button>
          </div>
        )}
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
                    <p className="text-sm font-medium text-gray-900">{rule.label}</p>
                    <p className="text-xs text-gray-500 mb-2">{rule.description}</p>
                    <div className="flex flex-wrap gap-2">
                      {LEVEL_OPTIONS.map((option) => (
                        <button
                          key={option.value} type="button" title={option.hint}
                          onClick={() => setLevels({ ...levels, [rule.key]: option.value })}
                          className={`px-3 py-1.5 text-sm rounded-full border transition-colors ${
                            levels[rule.key] === option.value
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
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
          No constraint profiles defined yet. Create one to get started.
        </div>
      )}
    </div>
  );
}
