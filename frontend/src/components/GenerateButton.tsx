import { useState, useEffect } from 'react';
import { timetableApi, constraintsApi } from '../api/client';
import { TimetableRun, ConstraintProfile } from '../types';
import { Play, RefreshCw, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

export function GenerateButton() {
  const [profiles, setProfiles] = useState<ConstraintProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentRun, setCurrentRun] = useState<TimetableRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProfiles();
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
      const response = await timetableApi.generate({ constraint_profile_id: selectedProfile });
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
                Timetable generated successfully! View it in the Timetable Runs page.
              </p>
            </div>
          )}

          {currentRun.status === 'failed' && currentRun.llm_explanation && (
            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <h4 className="font-medium text-red-800 mb-2">Why generation failed:</h4>
              <p className="text-sm text-red-700 whitespace-pre-wrap">{currentRun.llm_explanation}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}