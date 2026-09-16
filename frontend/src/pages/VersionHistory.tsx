import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { timetableApi } from '../api/client';
import { TimetableRun } from '../types';
import { ChevronLeft, CheckCircle } from 'lucide-react';

export function VersionHistory() {
  const { runId } = useParams<{ runId: string }>();
  const [versions, setVersions] = useState<TimetableRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState<number | null>(null);
  const [fromRun, setFromRun] = useState<number | null>(null);
  const [toRun, setToRun] = useState<number | null>(null);
  const [comparison, setComparison] = useState<any | null>(null);
  const navigate = useNavigate();

  const load = () => {
    setLoading(true);
    timetableApi.getVersions(parseInt(runId!))
      .then((res) => setVersions(res.data))
      .finally(() => setLoading(false));
  };

  useEffect(load, [runId]);

  const handlePublish = async (id: number) => {
    setPublishing(id);
    try {
      await timetableApi.publish(id);
      load();
    } finally {
      setPublishing(null);
    }
  };

  const handleCompare = async () => {
    if (!fromRun || !toRun || fromRun === toRun) return;
    try {
      const response = await timetableApi.compare(fromRun, toRun);
      setComparison(response.data);
    } catch (error) {
      console.error('Comparison failed:', error);
    }
  };

  if (loading) return <div className="text-sm text-gray-500">Loading...</div>;

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-4 mb-6">
        <Link to={`/runs/${runId}`} className="text-gray-600 hover:text-gray-900">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-gray-900">Version History</h1>
      </div>

      <div className="space-y-3">
        {versions.map((v, i) => (
          <div key={v.id} className={`bg-white rounded-lg border p-4 ${v.is_published ? 'border-green-300 ring-1 ring-green-200' : 'border-gray-200'}`}>
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900">
                    {i === 0 ? 'Original generation' : `Edit`} · Run #{v.id}
                  </span>
                  {v.is_published && (
                    <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                      <CheckCircle size={12} /> Published
                    </span>
                  )}
                </div>
                {v.change_summary && (
                  <p className="text-sm text-gray-600 mt-1">{v.change_summary}</p>
                )}
                <p className="text-xs text-gray-400 mt-1">{new Date(v.created_at).toLocaleString()}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => navigate(`/runs/${v.id}`)}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  View
                </button>
                {!v.is_published && (
                  <button
                    onClick={() => handlePublish(v.id)}
                    disabled={publishing === v.id}
                    className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg"
                  >
                    {publishing === v.id ? 'Publishing...' : 'Publish this version'}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {versions.length > 1 && (
        <div className="mt-6 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h2 className="font-semibold text-gray-900 mb-3">Compare versions</h2>
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={fromRun ?? ''}
              onChange={(event) => setFromRun(Number(event.target.value) || null)}
              className="px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
            >
              <option value="">From version</option>
              {versions.map((version) => <option key={version.id} value={version.id}>Run #{version.id}</option>)}
            </select>
            <span className="text-gray-500">to</span>
            <select
              value={toRun ?? ''}
              onChange={(event) => setToRun(Number(event.target.value) || null)}
              className="px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
            >
              <option value="">To version</option>
              {versions.map((version) => <option key={version.id} value={version.id}>Run #{version.id}</option>)}
            </select>
            <button
              onClick={handleCompare}
              disabled={!fromRun || !toRun || fromRun === toRun}
              className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              Compare
            </button>
          </div>
          {comparison && (
            <div className="mt-4 text-sm text-gray-700">
              <p className="font-medium">{comparison.summary.total_changes} total change(s): {comparison.summary.changed_classes} modified, {comparison.summary.added_classes} added, {comparison.summary.removed_classes} removed.</p>
              {comparison.changes.map((change: any, index: number) => (
                <p key={`${change.subject_id}-${index}`} className="mt-1">
                  {change.type}: {change.subject_id} ({change.entity_id}) {change.changes ? JSON.stringify(change.changes) : ''}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      <p className="text-xs text-gray-400 mt-4">
        Publishing an earlier version is how you roll back - nothing here is ever deleted.
      </p>
    </div>
  );
}
