import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { timetableApi, constraintsApi, yearsApi, sectionsApi, academicTermsApi } from '../api/client';
import { TimetableRun, ConstraintProfile, AcademicYear, Section, AcademicTerm, ScopeMode } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Play, RefreshCw, CheckCircle, XCircle, AlertCircle, AlertTriangle } from 'lucide-react';

export function GenerateButton() {
  const { departmentId } = useDepartment();
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<ConstraintProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [numAlternatives, setNumAlternatives] = useState(3);
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentRun, setCurrentRun] = useState<TimetableRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [selectedTerm, setSelectedTerm] = useState('');
  const [generationScope, setGenerationScope] = useState<'all' | 'year' | 'sections'>('all');
  const [selectedYear, setSelectedYear] = useState('');
  const [selectedSections, setSelectedSections] = useState<string[]>([]);
  const [scopeMode, setScopeMode] = useState<ScopeMode>('fit_into_existing');

  // setTimeout closures otherwise capture the isGenerating value from the
  // render that scheduled them - by the time the 5-minute timer fires,
  // that stale `false`/`true` never reflects a run that finished (or
  // didn't) in between, so the abort silently never fires. A ref always
  // reads the current value.
  const isGeneratingRef = useRef(isGenerating);
  useEffect(() => { isGeneratingRef.current = isGenerating; }, [isGenerating]);

  useEffect(() => {
    fetchProfiles();
    Promise.all([yearsApi.list(), sectionsApi.list(), academicTermsApi.list()])
      .then(([yearsResponse, sectionsResponse, termsResponse]) => {
        setYears(yearsResponse.data);
        setSections(sectionsResponse.data);
        setTerms(termsResponse.data);
        setSelectedYear(yearsResponse.data[0]?.id || '');
      })
      .catch((loadError) => console.error('Failed to fetch generation scope data:', loadError));
  }, []);

  const fetchProfiles = async () => {
    try {
      const response = await constraintsApi.listProfiles();
      setProfiles(response.data);
      if (response.data.length > 0) {
        setSelectedProfile(response.data[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch profiles:', error);
    }
  };

  const handleGenerate = async () => {
    if (!departmentId) {
      setError('No department is configured yet. Add one from Settings.');
      return;
    }
    if (!selectedProfile) {
      setError('Please select a scheduling priorities profile');
      return;
    }

    setIsGenerating(true);
    setError(null);
    setCurrentRun(null);

    try {
      const scope = generationScope === 'year'
        ? { year_ids: selectedYear ? [selectedYear] : [] }
        : generationScope === 'sections'
          ? { section_ids: selectedSections }
          : {};
      if (generationScope === 'year' && !selectedYear) {
        setError('Select an academic year first.');
        setIsGenerating(false);
        return;
      }
      if (generationScope === 'sections' && selectedSections.length === 0) {
        setError('Select at least one section first.');
        setIsGenerating(false);
        return;
      }
      const response = await timetableApi.generate({
        department_id: departmentId,
        constraint_profile_id: selectedProfile,
        term_id: selectedTerm || undefined,
        num_alternatives: numAlternatives,
        scope_mode: scopeMode,
        ...scope,
      });
      const run = response.data;
      setCurrentRun(run);

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const updatedRun = await timetableApi.getRun(run.id);
          setCurrentRun(updatedRun.data);

          if (updatedRun.data.status === 'completed' || updatedRun.data.status === 'failed') {
            clearInterval(pollInterval);
            setIsGenerating(false);
            if (updatedRun.data.status === 'completed') {
              // Land on the finished timetable instead of leaving the admin
              // on this page with a link to go find it elsewhere (Phase 3.9).
              navigate(`/runs/${updatedRun.data.id}`);
            }
          }
        } catch (error) {
          clearInterval(pollInterval);
          setIsGenerating(false);
          setError('Failed to check run status');
        }
      }, 2000);

      // Abort if the run is still going well past what the backend could
      // legitimately need. The backend caps each alternative's solve at its
      // own time budget (SOLVER_MAX_SECONDS, 300s by default) and solves
      // them one after another - so num_alternatives=3 can genuinely take
      // ~15 minutes. A fixed 5-minute abort fired on nearly every request
      // with the UI's own default of 3 alternatives, well before the
      // backend had a chance to finish (it wasn't hung, just still working).
      // 6 min/alternative plus a 2-minute buffer for model build/extraction/
      // validation covers that with room to spare.
      const abortMs = numAlternatives * 360000 + 120000;
      setTimeout(() => {
        clearInterval(pollInterval);
        if (isGeneratingRef.current) {
          setIsGenerating(false);
          setError(`Generation timed out after ${Math.round(abortMs / 60000)} minutes`);
        }
      }, abortMs);

    } catch (error: any) {
      setIsGenerating(false);
      setError(error.response?.data?.detail || 'Failed to start generation');
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={24} className="text-green-500" />;
      case 'failed':
        return <XCircle size={24} className="text-red-500" />;
      case 'solving':
        return <RefreshCw size={24} className="text-blue-500 animate-spin" />;
      default:
        return <AlertCircle size={24} className="text-gray-400" />;
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Generate Timetable</h2>
        <p className="text-gray-600">Create a clash-free timetable from the information you've entered.</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {!departmentId && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <AlertTriangle size={18} />
            No department is configured yet. Add one from Settings.
          </div>
        )}

        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Other years already have timetables
          </label>
          <div className="space-y-2">
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" checked={scopeMode === 'fit_into_existing'} onChange={() => setScopeMode('fit_into_existing')} className="mt-1" />
              <span>
                <span className="font-medium text-gray-900">Keep the other years' timetables valid (recommended)</span>
                <br />
                <span className="text-gray-600">Every already-published class outside this scope is treated as fixed - the new schedule can never clash with them.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" checked={scopeMode === 'fresh'} onChange={() => setScopeMode('fresh')} className="mt-1" />
              <span>
                <span className="font-medium text-gray-900">Ignore other years - I'll redo them too</span>
                <br />
                <span className="text-gray-600">Faster and more flexible, but it may clash with other sections or departments that share a teacher or room.</span>
              </span>
            </label>
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Scheduling priorities</label>
          <select
            value={selectedProfile}
            onChange={(e) => setSelectedProfile(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={isGenerating}
          >
            <option value="">Select a profile</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>{profile.name}</option>
            ))}
          </select>
        </div>

        {terms.filter((term) => term.department_id === departmentId).length > 0 && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">Term (optional)</label>
            <select
              value={selectedTerm}
              onChange={(e) => setSelectedTerm(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={isGenerating}
            >
              <option value="">No term selected</option>
              {terms.filter((term) => term.department_id === departmentId).map((term) => (
                <option key={term.id} value={term.id}>{term.name}</option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">Used for the calendar export's date range and the PDF's session date.</p>
          </div>
        )}

        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Generate timetable for</label>
          <select value={generationScope} onChange={(event) => setGenerationScope(event.target.value as 'all' | 'year' | 'sections')} disabled={isGenerating} className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white">
            <option value="all">All years and sections</option>
            <option value="year">One academic year</option>
            <option value="sections">Selected sections only</option>
          </select>
          {generationScope === 'year' && (
            <select value={selectedYear} onChange={(event) => setSelectedYear(event.target.value)} disabled={isGenerating} className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg bg-white">
              <option value="">Select academic year</option>
              {years.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}
            </select>
          )}
          {generationScope === 'sections' && (
            <div className="mt-3 space-y-2 rounded-lg border border-gray-200 bg-white p-3">
              <p className="text-xs text-gray-500">Select one or more sections. This is useful for testing one class such as third-year Section A.</p>
              {sections.map((section) => (
                <label key={section.id} className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={selectedSections.includes(section.id)}
                    onChange={(event) => setSelectedSections((current) => event.target.checked ? [...current, section.id] : current.filter((id) => id !== section.id))}
                    disabled={isGenerating}
                  />
                  {section.name} ({section.id})
                </label>
              ))}
              {sections.length === 0 && <p className="text-sm text-gray-500">No sections configured.</p>}
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Timetable alternatives</label>
          <select
            value={numAlternatives}
            onChange={(e) => setNumAlternatives(parseInt(e.target.value, 10))}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={isGenerating}
          >
            {[1, 2, 3, 4, 5].map((count) => (
              <option key={count} value={count}>
                {count === 1 ? 'Best timetable only' : `${count} alternatives`}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">We'll prepare a few timetables so you can pick the one you like.</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
            <AlertCircle size={20} className="text-red-600" />
            <span className="text-sm text-red-700">{error}</span>
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={isGenerating || !selectedProfile || !departmentId}
          className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isGenerating ? (
            <>
              <RefreshCw size={20} className="animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Play size={20} />
              Generate Timetable
            </>
          )}
        </button>
      </div>

      {currentRun && currentRun.status !== 'completed' && (
        <div className="mt-6 bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Status</h3>
            {getStatusIcon(currentRun.status)}
          </div>

          <div className="space-y-3">
            <div>
              <span className="text-sm font-medium text-gray-700">Status:</span>
              <span className={`ml-2 text-sm font-medium ${
                currentRun.status === 'failed' ? 'text-red-600' : 'text-blue-600'
              }`}>
                {currentRun.status}
              </span>
            </div>
            <div>
              <span className="text-sm font-medium text-gray-700">Started:</span>
              <span className="ml-2 text-sm text-gray-600">
                {new Date(currentRun.created_at).toLocaleString()}
              </span>
            </div>
          </div>

          {currentRun.status === 'failed' && currentRun.llm_explanation && (
            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <h4 className="font-medium text-red-800 mb-2">Why generation failed:</h4>
              <p className="text-sm text-red-700 whitespace-pre-wrap">{currentRun.llm_explanation}</p>
              <p className="text-xs text-red-700 mt-3">
                Fix the listed data in Setup, then generate again. Lab subjects need batches, and every class needs an eligible teacher and room with enough capacity.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
