import { useState } from 'react';
import { AcademicYearForm } from '../components/AcademicYearForm';
import { SectionForm } from '../components/SectionForm';
import { SubjectForm } from '../components/SubjectForm';
import { TeacherForm } from '../components/TeacherForm';
import { RoomForm } from '../components/RoomForm';
import { ConstraintBuilder } from '../components/ConstraintBuilder';
import { GenerateButton } from '../components/GenerateButton';
import { BulkExcelImport } from '../components/BulkExcelImport';
import { LabBatchForm } from '../components/LabBatchForm';
import { DataResetPanel } from '../components/DataResetPanel';
import { ScheduleSettings } from '../components/ScheduleSettings';
import { ChevronLeft, ChevronRight, Check } from 'lucide-react';

type Step = 'bulk-import' | 'years' | 'schedule' | 'sections' | 'subjects' | 'lab-batches' | 'teachers' | 'rooms' | 'constraints' | 'generate';

const steps: { id: Step; label: string; description: string }[] = [
  { id: 'bulk-import', label: 'Bulk Excel', description: 'Load setup data from a workbook' },
  { id: 'years', label: 'Academic Years', description: 'Define years and lunch breaks' },
  { id: 'schedule', label: 'Class Times', description: 'Customize days and time ranges' },
  { id: 'sections', label: 'Sections', description: 'Define sections per year' },
  { id: 'subjects', label: 'Subjects', description: 'Define subjects and requirements' },
  { id: 'lab-batches', label: 'Lab Batches', description: 'Split sections into lab groups' },
  { id: 'teachers', label: 'Teachers', description: 'Define teachers and availability' },
  { id: 'rooms', label: 'Rooms', description: 'Define rooms and equipment' },
  { id: 'constraints', label: 'Constraints', description: 'Set soft constraint weights' },
  { id: 'generate', label: 'Generate', description: 'Run the timetable solver' },
];

export function SetupWizard() {
  const [currentStep, setCurrentStep] = useState<Step>('years');
  
  const currentStepIndex = steps.findIndex(s => s.id === currentStep);
  
  const nextStep = () => {
    if (currentStepIndex < steps.length - 1) {
      setCurrentStep(steps[currentStepIndex + 1].id);
    }
  };
  
  const prevStep = () => {
    if (currentStepIndex > 0) {
      setCurrentStep(steps[currentStepIndex - 1].id);
    }
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case 'bulk-import':
        return <BulkExcelImport />;
      case 'years':
        return <AcademicYearForm />;
      case 'schedule':
        return <ScheduleSettings />;
      case 'sections':
        return <SectionForm />;
      case 'subjects':
        return <SubjectForm />;
      case 'lab-batches':
        return <LabBatchForm />;
      case 'teachers':
        return <TeacherForm />;
      case 'rooms':
        return <RoomForm />;
      case 'constraints':
        return <ConstraintBuilder />;
      case 'generate':
        return <GenerateButton />;
      default:
        return null;
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Timetable Setup Wizard</h1>
        <p className="text-gray-600">Configure all constraints to generate a conflict-free timetable</p>
      </div>

      <DataResetPanel />
      
      {/* Progress bar */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-2">
          {steps.map((step, index) => (
            <button
              key={step.id}
              type="button"
              aria-current={step.id === currentStep ? 'step' : undefined}
              onClick={() => setCurrentStep(step.id)}
              className="flex flex-col items-center rounded-md px-1 py-1 hover:bg-gray-50"
            >
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                index === currentStepIndex
                  ? 'bg-blue-600 text-white'
                  : index < currentStepIndex
                  ? 'bg-green-500 text-white'
                  : 'bg-gray-200 text-gray-600'
              }`}>
                {index < currentStepIndex ? <Check size={20} /> : index + 1}
              </div>
              <span className="text-xs mt-1 text-center text-gray-600">{step.label}</span>
            </button>
          ))}
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div 
            className="h-full bg-blue-600 transition-all duration-300"
            style={{ width: `${((currentStepIndex + 1) / steps.length) * 100}%` }}
          />
        </div>
      </div>
      
      {/* Step info */}
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900">{steps[currentStepIndex].label}</h2>
        <p className="text-gray-600">{steps[currentStepIndex].description}</p>
      </div>
      
      {/* Step content */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        {renderStepContent()}
      </div>
      
      {/* Navigation */}
      <div className="flex justify-between">
        <button
          onClick={prevStep}
          disabled={currentStepIndex === 0}
          className="flex items-center gap-2 px-4 py-2 text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft size={20} />
          Previous
        </button>
        <button
          onClick={nextStep}
          disabled={currentStepIndex === steps.length - 1}
          className="flex items-center gap-2 px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Next
          <ChevronRight size={20} />
        </button>
      </div>
    </div>
  );
}
