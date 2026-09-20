import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { departmentsApi } from '../api/client';
import { Department } from '../types';

interface DepartmentContextValue {
  departments: Department[];
  departmentId: string;
  setDepartmentId: (id: string) => void;
  refresh: () => void;
}

const DepartmentContext = createContext<DepartmentContextValue | undefined>(undefined);

export function DepartmentProvider({ children }: { children: ReactNode }) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentIdState] = useState<string>(() => localStorage.getItem('active_department_id') || '');

  const refresh = () => {
    departmentsApi.list().then((response) => {
      setDepartments(response.data);
      // If nothing (or a now-deleted department) is selected, default to the first one available.
      if (response.data.length && !response.data.some((d: Department) => d.id === departmentId)) {
        setDepartmentId(response.data[0].id);
      }
    }).catch(() => setDepartments([]));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setDepartmentId = (id: string) => {
    setDepartmentIdState(id);
    localStorage.setItem('active_department_id', id);
  };

  return (
    <DepartmentContext.Provider value={{ departments, departmentId, setDepartmentId, refresh }}>
      {children}
    </DepartmentContext.Provider>
  );
}

export function useDepartment() {
  const context = useContext(DepartmentContext);
  if (!context) throw new Error('useDepartment must be used within a DepartmentProvider');
  return context;
}
