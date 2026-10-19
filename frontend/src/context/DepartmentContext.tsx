import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { departmentsApi } from '../api/client';
import { Department } from '../types';
import { useAuth } from './AuthContext';

interface DepartmentContextValue {
  departments: Department[];
  departmentId: string;
  setDepartmentId: (id: string) => void;
  refresh: () => void;
}

const DepartmentContext = createContext<DepartmentContextValue | undefined>(undefined);

export function DepartmentProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentIdState] = useState<string>(() => localStorage.getItem('active_department_id') || '');

  const refresh = () => {
    departmentsApi.list().then((response) => {
      // Everyone but the superadmin is pinned to the department on their
      // account server-side - the picker must not offer (or silently fall
      // back to) any other one.
      const pinned = user && user.role !== 'SUPERADMIN';
      const scoped = pinned
        ? response.data.filter((d: Department) => d.id === user.department_id)
        : response.data;
      setDepartments(scoped);
      if (pinned) {
        if (user.department_id) setDepartmentId(user.department_id);
        return;
      }
      // If nothing (or a now-deleted department) is selected, default to the first one available.
      if (scoped.length && !scoped.some((d: Department) => d.id === departmentId)) {
        setDepartmentId(scoped[0].id);
      }
    }).catch(() => setDepartments([]));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role, user?.department_id]);

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
