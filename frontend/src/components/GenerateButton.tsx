import { useState, useEffect } from 'react';
import { timetableApi, constraintsApi, yearsApi, sectionsApi } from '../api/client';
import { TimetableRun, ConstraintProfile, AcademicYear, Section } from '../types';
import { Play, RefreshCw, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

export function GenerateButton() {
  const [profiles, setProfiles] = useState<ConstraintProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [numAlternatives, setNumAlternatives] = useState(3);
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentRun, setCurrentRun] = useState<TimetableRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [generationScope, setGenerationScope] = useState<'all' | 'year' | 'sections'>('all');
  const [selectedYear, setSelectedYear] = useState('');
  const [selectedSections, setSelectedSections] = useState<string[]>([]);

  useEffect(() => {
    fetchProfiles();
    Promise.all([yearsApi.list(), sectionsApi.list()])
      .then(([yearsResponse, sectionsResponse]) => {
        setYears(yearsResponse.data);
        setSections(sectionsResponse.data);
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
    if (!selectedProfile) {
      setError('Please select a constraint profile');
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
        constraint_profile_id: selectedProfile,
        num_alternatives: numAlternatives,
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
          }
        } catch (error) {
          clearInterval(pollInterval);
          setIsGenerating(false);
          setError('Failed to check run status');
        }
      }, 2000);
      
      // Timeout after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        if (isGenerating) {
          setIsGenerating(false);
          setError('Generation timed out after 5 minutes');
        }
      }, 300000);
      
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

  const makeFailureReadable = (message: string) => message
    .replace(/\[lab_without_batch\]/g, 'Missing lab batches: ')
    .replace(/\[no_eligible_room\]/g, 'No suitable room: ')
    .replace(/\[no_eligible_teacher\]/g, 'No teacher is assigned to teach: ')
    .replace(/\[no_eligible_lab_room\]/g, 'No suitable lab room: ')
    .replace(/\[no_eligible_lab_teacher\]/g, 'No teacher is assigned to teach the lab: ')
    .replace(/\[section_hours_exceed_slots\]/g, 'Too many classes for the available weekly periods: ');

  return (
    <div className="max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Generate Timetable</h2>
        <p className="text-gray-600">Run the CP-SAT solver to generate a conflict-free timetable</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Constraint Profile</label>
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
          <p className="text-xs text-gray-500 mt-1">Each option is generated by CP-SAT and differs from earlier solutions.</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
            <AlertCircle size={20} className="text-red-600" />
            <span className="text-sm text-red-700">{error}</span>
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={isGenerating || !selectedProfile}
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

      {currentRun && (
        <div className="mt-6 bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Run Status</h3>
            {getStatusIcon(currentRun.status)}
          </div>
          
          <div className="space-y-3">
            <div>
              <span className="text-sm font-medium text-gray-700">Status:</span>
              <span className={`ml-2 text-sm font-medium ${
                currentRun.status === 'completed' ? 'text-green-600' :
                currentRun.status === 'failed' ? 'text-red-600' :
                'text-blue-600'
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
            {currentRun.completed_at && (
              <div>
                <span className="text-sm font-medium text-gray-700">Completed:</span>
                <span className="ml-2 text-sm text-gray-600">
                  {new Date(currentRun.completed_at).toLocaleString()}
                </span>
              </div>
            )}
          </div>

          {currentRun.status === 'completed' && (
            <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
              <p className="text-sm text-green-700">
                Timetable generated successfully! {currentRun.solver_output?.alternatives?.length || 1} timetable option(s) are available in the Timetable Runs page. Open a run, choose an alternative, and click “Use this alternative” to create a version.
              </p>
            </div>
          )}

          {currentRun.status === 'failed' && currentRun.llm_explanation && (
            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <h4 className="font-medium text-red-800 mb-2">Why generation failed:</h4>
              <p className="text-sm text-red-700 whitespace-pre-wrap">{makeFailureReadable(currentRun.llm_explanation)}</p>
              <p className="text-xs text-red-700 mt-3">
                Fix the listed data in Setup Wizard, then generate again. Lab subjects need batches, and every class needs an eligible teacher and room with enough capacity.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
