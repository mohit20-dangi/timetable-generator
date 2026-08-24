import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { timetableApi } from '../api/client';
import { TimetableRun } from '../types';
import { Calendar, CheckCircle, XCircle, RefreshCw, Clock } from 'lucide-react';

export function TimetableRuns() {
  const [runs, setRuns] = useState<TimetableRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRuns();
  }, []);

  const fetchRuns = async () => {
    try {
      const response = await timetableApi.listRuns();
      setRuns(response.data);
    } catch (error) {
      console.error('Failed to fetch runs:', error);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={20} className="text-green-500" />;
      case 'failed':
        return <XCircle size={20} className="text-red-500" />;
      case 'solving':
        return <RefreshCw size={20} className="text-blue-500 animate-spin" />;
      default:
        return <Clock size={20} className="text-gray-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      case 'solving':
        return 'bg-blue-100 text-blue-800';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <RefreshCw size={32} className="animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Timetable Runs</h1>
        <Link
          to="/"
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          New Generation
        </Link>
      </div>

      {runs.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <Calendar size={48} className="mx-auto text-gray-400 mb-4" />
          <p className="text-gray-500">No timetable runs yet. Generate one from the Setup Wizard.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {runs.map((run) => (
            <div key={run.id} className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {getStatusIcon(run.status)}
                  <div>
                    <h3 className="font-semibold text-gray-900">Run #{run.id}</h3>
                    <p className="text-sm text-gray-600">
                      Created: {new Date(run.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(run.status)}`}>
                  {run.status}
                </span>
              </div>
              
              {run.status === 'completed' && (
                <Link
                  to={`/runs/${run.id}`}
                  className="mt-3 inline-block text-blue-600 hover:text-blue-800 text-sm font-medium"
                >
                  View Timetable →
                </Link>
              )}
              
              {run.status === 'failed' && run.llm_explanation && (
                <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-sm text-red-700 line-clamp-3">{run.llm_explanation}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}