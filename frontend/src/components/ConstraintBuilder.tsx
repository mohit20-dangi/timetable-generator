import { useState, useEffect } from 'react';
import { constraintsApi } from '../api/client';
import { ConstraintProfile } from '../types';
import { Plus, Save, X, Send, AlertCircle, CheckCircle } from 'lucide-react';

export function ConstraintBuilder() {
  const [profiles, setProfiles] = useState<ConstraintProfile[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingProfile, setEditingProfile] = useState<ConstraintProfile | null>(null);
  const [formData, setFormData] = useState<{ id: string; name: string; soft_constraint_weights: Record<string, number> }>({
    id: '',
    name: '',
    soft_constraint_weights: {
      minimize_gaps: 5,
      lab_theory_mix: 3,
      teacher_preference: 2,
      empty_day_preference: 2,
      minimize_travel: 3,
      class_changes_via_breaks: 5
    }
  });
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingProfile) {
        // Update logic would go here
      } else {
        await constraintsApi.createProfile(formData);
      }
      setShowForm(false);
      setEditingProfile(null);
      setFormData({
        id: '',
        name: '',
        soft_constraint_weights: {
          minimize_gaps: 5,
          lab_theory_mix: 3,
          teacher_preference: 2,
          empty_day_preference: 2,
          minimize_travel: 3,
          class_changes_via_breaks: 5
        }
      });
      fetchProfiles();
    } catch (error) {
      console.error('Failed to save profile:', error);
    }
  };

  const handleEdit = (profile: ConstraintProfile) => {
    setEditingProfile(profile);
    setFormData({
      id: profile.id,
      name: profile.name,
      soft_constraint_weights: profile.soft_constraint_weights || {
        minimize_gaps: 5,
        lab_theory_mix: 3,
        teacher_preference: 2,
        empty_day_preference: 2,
        minimize_travel: 3,
        class_changes_via_breaks: 5
      }
    });
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
      setNlError(error.response?.data?.detail || 'Failed to parse constraints');
    } finally {
      setNlLoading(false);
    }
  };

  const handleNLImport = () => {
    if (nlResult) {
      setFormData({
        id: `profile_${Date.now()}`,
        name: 'Imported from NL',
        soft_constraint_weights: nlResult.soft_constraint_weights || {
          minimize_gaps: 5,
          lab_theory_mix: 3,
          teacher_preference: 2,
          empty_day_preference: 2
        }
      });
      setShowForm(true);
      setNlResult(null);
      setNlText('');
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Constraint Profiles</h3>
        <button
          onClick={() => {
            setShowForm(true);
            setEditingProfile(null);
            setFormData({
              id: '',
              name: '',
              soft_constraint_weights: {
                minimize_gaps: 5,
                lab_theory_mix: 3,
                teacher_preference: 2,
                empty_day_preference: 2
              }
            });
          }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Profile
        </button>
      </div>

      {/* Natural Language Constraint Parsing */}
      <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
        <h4 className="font-medium text-gray-700 mb-2">Parse Natural Language Constraints</h4>
        <p className="text-sm text-gray-600 mb-3">
          Describe your constraints in plain English and the LLM will parse them into structured JSON.
        </p>
        <textarea
          value={nlText}
          onChange={(e) => setNlText(e.target.value)}
          placeholder="e.g., We have 3 years with 4 sections each. 1st year has 6 theory subjects and 3 labs. Lunch break is 1-2pm for all years. Prof. Sharma teaches Data Structures and is available Mon-Fri 9am-4pm..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-y min-h-[100px]"
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
                Parsing...
              </>
            ) : (
              <>
                <Send size={20} />
                Parse with LLM
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
              <span className="font-medium text-green-800">Constraints parsed successfully!</span>
            </div>
            <pre className="text-xs text-gray-700 bg-white p-3 rounded border overflow-x-auto max-h-60">
              {JSON.stringify(nlResult, null, 2)}
            </pre>
            <button
              onClick={handleNLImport}
              className="mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
            >
              Import as Profile
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
                  type="text"
                  value={formData.id}
                  onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., default"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Profile Name</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., Default Constraints"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Soft Constraint Weights</label>
              <div className="space-y-3">
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Minimize Gaps (students/teachers)</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.minimize_gaps}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.minimize_gaps}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        minimize_gaps: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Lab/Theory Mix</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.lab_theory_mix}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.lab_theory_mix}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        lab_theory_mix: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Teacher Preference</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.teacher_preference}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.teacher_preference}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        teacher_preference: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Empty Day Preference</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.empty_day_preference}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.empty_day_preference}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        empty_day_preference: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Minimize Travel Distance</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.minimize_travel}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.minimize_travel}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        minimize_travel: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="flex justify-between">
                    <span className="text-sm text-gray-700">Class Changes Via Breaks</span>
                    <span className="text-sm font-medium text-gray-900">{formData.soft_constraint_weights.class_changes_via_breaks}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={formData.soft_constraint_weights.class_changes_via_breaks}
                    onChange={(e) => setFormData({
                      ...formData,
                      soft_constraint_weights: {
                        ...formData.soft_constraint_weights,
                        class_changes_via_breaks: parseInt(e.target.value)
                      }
                    })}
                    className="w-full"
                  />
                </div>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <Save size={20} />
                {editingProfile ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingProfile(null);
                }}
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
              <th className="text-left px-4 py-2 font-medium text-gray-700">Weights</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((profile) => (
              <tr key={profile.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{profile.id}</td>
                <td className="px-4 py-2">{profile.name}</td>
                <td className="px-4 py-2">
                  <pre className="text-xs text-gray-600">
                    {JSON.stringify(profile.soft_constraint_weights, null, 2)}
                  </pre>
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => handleEdit(profile)}
                    className="p-1 text-blue-600 hover:bg-blue-100 rounded"
                  >
                    <Save size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(profile.id)}
                    className="p-1 text-red-600 hover:bg-red-100 rounded"
                  >
                    <X size={16} />
                  </button>
                </td>
              </tr>
            ))}
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