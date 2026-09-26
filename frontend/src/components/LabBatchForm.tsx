import { useEffect, useState } from 'react';
import { constraintsApi, sectionsApi, subjectsApi } from '../api/client';
import { Section, LabBatch, Subject, BatchPreflightResult } from '../types';
import { Plus, Trash2, Users, CheckCircle2, AlertTriangle } from 'lucide-react';

export function LabBatchForm() {
  const [sections, setSections] = useState<Section[]>([]);
  const [batches, setBatches] = useState<LabBatch[]>([]);
  const [labSubjects, setLabSubjects] = useState<Subject[]>([]);
  const [sectionId, setSectionId] = useState('');
  const [preflightSubjectId, setPreflightSubjectId] = useState('');
  const [preflight, setPreflight] = useState<BatchPreflightResult | null>(null);
  const [preflightError, setPreflightError] = useState('');
  const [formData, setFormData] = useState({ id: '', batch_name: '', strength: 20 });
  const [error, setError] = useState('');

  const load = async () => {
    const [sectionResponse, subjectResponse] = await Promise.all([sectionsApi.list(), subjectsApi.list()]);
    setSections(sectionResponse.data);
    setLabSubjects(subjectResponse.data.filter((s: Subject) => s.type === 'lab'));
    const selected = sectionId || sectionResponse.data[0]?.id || '';
    if (!sectionId) setSectionId(selected);
    if (selected) {
      const batchResponse = await constraintsApi.getLabBatches(selected);
      setBatches(batchResponse.data);
    }
  };

  useEffect(() => {
    load().catch(() => setError('Could not load sections or lab batches.'));
  }, []);

  const loadBatches = async (nextSectionId: string) => {
    setSectionId(nextSectionId);
    setPreflight(null);
    if (!nextSectionId) return;
    try {
      const response = await constraintsApi.getLabBatches(nextSectionId);
      setBatches(response.data);
    } catch {
      setError('Could not load batches for this section.');
    }
  };

  const runPreflight = async () => {
    setPreflightError('');
    setPreflight(null);
    if (!sectionId || !preflightSubjectId) {
      setPreflightError('Pick a lab subject to check.');
      return;
    }
    try {
      const response = await constraintsApi.preflightLabBatches(sectionId, preflightSubjectId);
      setPreflight(response.data);
    } catch (requestError: any) {
      setPreflightError(requestError?.response?.data?.detail || 'Could not check feasibility for this subject.');
    }
  };

  const addBatch = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!sectionId || !formData.id || !formData.batch_name || formData.strength < 1) {
      setError('Enter a batch ID, name, and a student strength greater than zero.');
      return;
    }
    try {
      await constraintsApi.createLabBatch({ ...formData, section_id: sectionId });
      setFormData({ id: '', batch_name: '', strength: 20 });
      await loadBatches(sectionId);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'Could not create the lab batch.');
    }
  };

  const deleteBatch = async (id: string) => {
    try {
      await constraintsApi.deleteLabBatch(id);
      await loadBatches(sectionId);
    } catch {
      setError('Could not delete the lab batch.');
    }
  };

  return (
    <div className="max-w-3xl">
      <div className="flex items-start gap-4 mb-5">
        <div className="p-3 rounded-xl bg-green-50 text-green-700"><Users size={26} /></div>
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Lab Batches</h3>
          <p className="text-sm text-gray-600 mt-1">
            A batch is a smaller student group that attends lab sessions together. For a class of 40,
            create Batch A with strength 20 and Batch B with strength 20.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 mb-5 text-sm text-blue-900">
        Batches belong to a section, not to one particular lab subject. The same batches can attend every lab
        subject for that section. How they're scheduled relative to each other - in parallel (different rooms),
        sequentially (never at the same time), or merged (combined into one class) - is set per lab subject, in
        that subject's "Lab batches scheduling" field.
      </div>

      <div className="mb-5">
        <label className="block text-sm font-medium text-gray-700 mb-1">Section</label>
        <select value={sectionId} onChange={(event) => loadBatches(event.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white">
          {sections.map((section) => <option key={section.id} value={section.id}>{section.name} ({section.strength} students)</option>)}
        </select>
      </div>

      <form onSubmit={addBatch} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end mb-5">
        <label className="text-sm text-gray-700">Batch ID<input value={formData.id} onChange={(event) => setFormData({ ...formData, id: event.target.value })} placeholder="cse1a_b1" className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" /></label>
        <label className="text-sm text-gray-700">Batch name<input value={formData.batch_name} onChange={(event) => setFormData({ ...formData, batch_name: event.target.value })} placeholder="Batch A" className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" /></label>
        <label className="text-sm text-gray-700">Students<input type="number" min="1" value={formData.strength} onChange={(event) => setFormData({ ...formData, strength: event.target.value === '' ? 0 : Number(event.target.value) })} className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" /></label>
        <button type="submit" className="flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"><Plus size={18} /> Add batch</button>
      </form>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}
      {(() => {
        const section = sections.find((s) => s.id === sectionId);
        if (!section || batches.length === 0) return null;
        const total = batches.reduce((sum, b) => sum + b.strength, 0);
        if (total >= section.strength) return null;
        return (
          <p className="mb-4 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
            These batches add up to {total} of {section.strength} students in {section.name} - the rest aren't in any batch yet.
          </p>
        );
      })()}
      <div className="space-y-2">
        {batches.map((batch) => (
          <div key={batch.id} className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
            <div><p className="font-medium text-gray-900">{batch.batch_name}</p><p className="text-xs text-gray-500">ID: {batch.id} · {batch.strength} students</p></div>
            <button type="button" onClick={() => deleteBatch(batch.id)} className="p-2 text-red-600 hover:bg-red-50 rounded-lg" aria-label={`Delete ${batch.batch_name}`}><Trash2 size={17} /></button>
          </div>
        ))}
        {batches.length === 0 && <p className="text-sm text-gray-500">No batches yet for this section.</p>}
      </div>

      {batches.length > 1 && (
        <div className="mt-6 rounded-lg border border-gray-200 p-4">
          <h4 className="font-medium text-gray-900 mb-1">Check batch-scheduling feasibility</h4>
          <p className="text-sm text-gray-600 mb-3">
            Each lab subject's own "batches scheduling" setting (parallel/sequential/merged) is edited on the
            subject itself. Pick a lab subject to check whether these {batches.length} batches can actually run
            that way - enough rooms, and enough qualified teachers - before generating.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-gray-700">
              Lab subject
              <select
                value={preflightSubjectId} onChange={(event) => { setPreflightSubjectId(event.target.value); setPreflight(null); }}
                className="mt-1 block w-64 px-3 py-2 border border-gray-300 rounded-lg bg-white"
              >
                <option value="">Select a subject...</option>
                {labSubjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <button type="button" onClick={runPreflight} className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
              Check feasibility
            </button>
          </div>
          {preflightError && <p className="mt-2 text-sm text-red-700">{preflightError}</p>}
          {preflight && (
            <div className={`mt-3 rounded-lg border p-3 text-sm ${preflight.feasible ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
              <div className="flex items-center gap-2 font-medium">
                {preflight.feasible ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                {preflight.feasible
                  ? `These batches can run in "${preflight.mode}" mode.`
                  : `These batches can't run in "${preflight.mode}" mode yet.`}
              </div>
              <p className="mt-1">
                {preflight.batch_count} batches ({preflight.combined_strength} students combined),{' '}
                {preflight.rooms_available_in_common_slot} suitable room(s), {preflight.qualified_teachers} qualified teacher(s).
              </p>
              {preflight.issues.map((issue, i) => <p key={i} className="mt-1">{issue.message}</p>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
