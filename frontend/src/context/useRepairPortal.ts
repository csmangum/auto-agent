import { useContext } from 'react';
import { RepairPortalContext } from './repairPortalContext';

export function useRepairPortal() {
  const ctx = useContext(RepairPortalContext);
  if (!ctx) throw new Error('useRepairPortal must be used within RepairPortalProvider');
  return ctx;
}
