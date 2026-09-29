import { useState, useEffect } from 'react';
import { sectionsApi } from '../api/client';
import { Section, Subject, SectionSubjectLink } from '../types';
import { Save, Layers } from 'lucide-react';

interface ElectiveGroupEditorProps {
  sections: Section[];
  subjects: Subject[];
  onSaved: () => void;
}

export function ElectiveGroupEditor({ sections, subjects, onSaved }: ElectiveGroupEditorProps) {
  const [sectionId, setSectionId] = useState('');
  const [localLinks, setLocalLinks] = useState<SectionSubjectLink[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const section = sections.find((s) => s.id === sectionId);
    setLocalLinks(section ? section.subjects.map((l) => ({ ...l })) : []);
    setSaved(false);
  }, [sectionId, sections]);

  const updateLink = (subjectId: string, patch: Partial<SectionSubjectLink>) => {
    setSaved(false);
    setLocalLinks((prev) =>
      prev.map((l) => (l.subject_id === subjectId ? { ...l, ...patch } : l))
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      for (const link of localLinks) {
        await sectionsApi.addSubject(sectionId, {
          subject_id: link.subject_id,
          is_elective: link.is_elective,
          elective_group_id: link.is_elective ? (link.elective_group_id || null) : null,
        });
      }
      setSaved(true);
      onSaved();
    } catch (error) {
      console.error('Failed to save elective settings:', error);
    } finally {
      setSaving(false);
    }
  };

  if (sections.length === 0 || subjects.length === 0) return null;

  return (
    <div className="mt-8">
      <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
        <Layers size={20} />
        Elective Groups
      </h3>
      <p className="text-sm text-gray-600 mb-3">
        Mark subjects within a section as electives and give matching ones the same group name
        (e.g. "elective_1"). Subjects in the same group are scheduled at the same time, so a
        student can attend whichever one they picked without a clash. Only subjects already
        assigned to the section (above) can be marked here.
      </p>

      <select
        value={sectionId}
        onChange={(e) => setSectionId(e.target.value)}
        className="mb-3 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      >
        <option value="">Select a section</option>
        {sections.map((s) => (
          <option key={s.id} value={s.id}>{s.name}</option>
        ))}
      </select>

      {sectionId && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-100">
                <th className="text-left px-4 py-2 font-medium text-gray-700">Subject</th>
                <th className="text-left px-4 py-2 font-medium text-gray-700">Elective?</th>
                <th className="text-left px-4 py-2 font-medium text-gray-700">Group</th>
              </tr>
            </thead>
            <tbody>
              {localLinks.map((link) => {
                const subject = subjects.find((s) => s.id === link.subject_id);
                return (
                  <tr key={link.subject_id} className="border-b border-gray-200">
                    <td className="px-4 py-2">{subject?.name || link.subject_id}</td>
                    <td className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={link.is_elective}
                        onChange={(e) =>
                          updateLink(link.subject_id, {
                            is_elective: e.target.checked,
                            elective_group_id: e.target.checked ? link.elective_group_id : null,
                          })
                        }
                        className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <input
                        type="text"
                        value={link.elective_group_id || ''}
                        onChange={(e) => updateLink(link.subject_id, { elective_group_id: e.target.value })}
                        disabled={!link.is_elective}
                        placeholder="e.g. elective_1"
                        className="px-2 py-1 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                    </td>
                  </tr>
                );
              })}
              {localLinks.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-4 text-center text-gray-500">
                    No subjects assigned to this section yet - assign some above first.
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {localLinks.length > 0 && (
            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                <Save size={18} />
                {saving ? 'Saving...' : 'Save Elective Settings'}
              </button>
              {saved && <span className="text-sm text-green-600">Saved</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
