import { apiClient } from './client';
import type { TrainingPlanRequest, TrainingPlanResponse } from './types';

export const trainingApi = {
  createPlan: (employeeId: string, data: TrainingPlanRequest) =>
    apiClient.post<TrainingPlanResponse>(`/training/plan/${employeeId}`, data),

  getPlan: (employeeId: string) =>
    apiClient.get<TrainingPlanResponse>(`/training/plan/${employeeId}`),
};
