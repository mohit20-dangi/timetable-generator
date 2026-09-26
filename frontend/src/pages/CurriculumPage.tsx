import { useEffect, useMemo, useState } from 'react';
import { sectionsApi, subjectsApi, constraintsApi, yearsApi, subjectTypesApi } from '../api/client';
import { Section, Subject, AcademicYear, SubjectType } from '../types';
import { Search, Copy, Plus, X, AlertTriangle } from 'lucide-react';

/** Phase 3.3: replaces the old "one column per subject" matrix. A section
 * on the left, its assigned subjects on the right, with a copy-from-another-
 * section shortcut and a running contact-hours total against what the bell
 * schedule actually offers - the number that tells an admin immediately
 * whether the week is oversubscribed, before they ever click Generate. */
export function CurriculumPage() {
  const [sections, setSections] = useState<Section[]>([]);
  const [years, setYears] = useState<Record<string, AcademicYear>>({});
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectTypes, setSubjectTypes] = useState<SubjectType[]>([]);
  const [selectedSection, setSelectedSection] = useState('');
  const [assigned, setAssigned] = useState<Record<string, string[]>>({});
  const [periodsPerWeek, setPeriodsPerWeek] = useState(0);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [copyFrom, setCopyFrom] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([sectionsApi.list(), subjectsApi.list(), yearsApi.list(), subjectTypesApi.list(), constraintsApi.listTimeSlots()])
      .then(([sectionsRes, subjectsRes, yearsRes, typesRes, slotsRes]) => {
        setSections(sectionsRes.data);
        setSubjects(subjectsRes.data);
        setSubjectTypes(typesRes.data);
        const yearMap: Record<string, AcademicYear> = {};
        yearsRes.data.forEach((y: AcademicYear) => { yearMap[y.id] = y; });
        setYears(yearMap);
        setPeriodsPerWeek(slotsRes.data.length);
        if (sectionsRes.data.length) setSelectedSection(sectionsRes.data[0].id);
      })
      .catch(() => setError('Could not load curriculum data.'));
  }, []);

  useEffect(() => {
    if (!selectedSection || assigned[selectedSection]) return;
    loadSection(selectedSection);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSection]);

  const loadSection = async (sectionId: string) => {
    try {
      const res = await constraintsApi.getSectionSubjects(sectionId);
      setAssigned((current) => ({ ...current, [sectionId]: res.data.map((ss: any) => ss.subject_id) }));
    } catch {
      setError('Could not load this section\'s subjects.');
    }
  };

  const currentAssigned = assigned[selectedSection] || [];
  const subjectById = useMemo(() => Object.fromEntries(subjects.map((s) => [s.id, s])), [subjects]);

  const totalContactHours = currentAssigned.reduce((sum, id) => sum + (subjectById[id]?.weekly_hours || 0), 0);
  const overSubscribed = periodsPerWeek > 0 && totalContactHours > periodsPerWeek;

  const categories = useMemo(() => [...new Set(subjects.map((s) => s.category).filter(Boolean))] as string[], [subjects]);

  const filteredSubjects = subjects.filter((s) => {
    if (search && !`${s.id} ${s.name}`.toLowerCase().includes(search.toLowerCase())) return false;
    if (typeFilter && s.type !== typeFilter) return false;
    if (categoryFilter && s.category !== categoryFilter) return false;
    return true;
  });

  const toggle = async (subjectId: string) => {
    if (!selectedSection || busy) return;
    setBusy(true);
    setError('');
    const isAssigned = currentAssigned.includes(subjectId);
    try {
      if (isAssigned) {
        await constraintsApi.removeSectionSubject(selectedSection, subjectId);
        setAssigned((current) => ({ ...current, [selectedSection]: current[selectedSection].filter((id) => id !== subjectId) }));
      } else {
        await constraintsApi.addSectionSubject({ section_id: selectedSection, subject_id: subjectId });
        setAssigned((current) => ({ ...current, [selectedSection]: [...(current[selectedSection] || []), subjectId] }));
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not update this assignment.');
    } finally {
      setBusy(false);
    }
  };

  const copyFromSection = async () => {
    if (!copyFrom || !selectedSection || busy) return;
    setBusy(true);
    setError('');
    try {
      let sourceIds = assigned[copyFrom];
      if (!sourceIds) {
        const res = await constraintsApi.getSectionSubjects(copyFrom);
        sourceIds = res.data.map((ss: any) => ss.subject_id);
        setAssigned((current) => ({ ...current, [copyFrom]: sourceIds }));
      }
      const toAdd = sourceIds.filter((id) => !currentAssigned.includes(id));
      for (const subjectId of toAdd) {
        await constraintsApi.addSectionSubject({ section_id: selectedSection, subject_id: subjectId });
      }
      setAssigned((current) => ({ ...current, [selectedSection]: [...currentAssigned, ...toAdd] }));
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not copy subjects from that section.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Curriculum</h1>
        <p className="text-gray-600">Assign subjects to each section.</p>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6">
        <div className="space-y-1">
          {sections.map((section) => {
            const year = years[section.year_id];
            return (
              <button
                key={section.id}
                onClick={() => setSelectedSection(section.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedSection === section.id ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <div className="font-medium">{section.name}</div>
                {year && <div className={`text-xs ${selectedSection === section.id ? 'text-blue-100' : 'text-gray-400'}`}>{year.name}</div>}
              </button>
            );
          })}
          {sections.length === 0 && <p className="text-sm text-gray-500">No sections yet.</p>}
        </div>

        <div>
          {selectedSection ? (
            <>
              <div className={`mb-4 flex items-center justify-between rounded-lg border p-3 text-sm ${overSubscribed ? 'border-red-200 bg-red-50 text-red-800' : 'border-gray-200 bg-gray-50 text-gray-700'}`}>
                <span className="flex items-center gap-2">
                  {overSubscribed && <AlertTriangle size={16} />}
                  Total contact hours/week: <strong>{totalContactHours}</strong>
                  {periodsPerWeek > 0 && <> of {periodsPerWeek} periods offered</>}
                </span>
                {overSubscribed && <span className="font-medium">Oversubscribed - the week doesn't have enough periods.</span>}
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                <div className="relative flex-1 min-w-[160px]">
                  <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search subjects" className="w-full rounded-lg border border-gray-300 py-1.5 pl-8 pr-2 text-sm" />
                </div>
                <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
                  <option value="">All types</option>
                  {subjectTypes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
                {categories.length > 0 && (
                  <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="">All categories</option>
                    {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                )}
                <div className="flex items-center gap-1 ml-auto">
                  <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="">Copy from section...</option>
                    {sections.filter((s) => s.id !== selectedSection).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <button onClick={copyFromSection} disabled={!copyFrom || busy} className="flex items-center gap-1 rounded-lg border border-gray-300 px-2 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                    <Copy size={14} /> Copy
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {filteredSubjects.map((subject) => {
                  const isAssigned = currentAssigned.includes(subject.id);
                  return (
                    <button
                      key={subject.id}
                      onClick={() => toggle(subject.id)}
                      disabled={busy}
                      className={`flex items-center justify-between rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-60 ${
                        isAssigned ? 'border-blue-300 bg-blue-50' : 'border-gray-200 bg-white hover:bg-gray-50'
                      }`}
                    >
                      <span>
                        <span className="font-medium text-gray-900">{subject.name}</span>
                        <span className="ml-1 text-xs text-gray-500">({subject.id})</span>
                      </span>
                      {isAssigned ? <X size={16} className="text-blue-600" /> : <Plus size={16} className="text-gray-400" />}
                    </button>
                  );
                })}
                {filteredSubjects.length === 0 && <p className="text-sm text-gray-500 col-span-2">No subjects match.</p>}
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">Select a section to assign subjects.</p>
          )}
        </div>
      </div>
    </div>
  );
}
