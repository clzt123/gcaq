import { apiClient } from './client';
import type { TrainingPlanRequest, TrainingPlanResponse } from './types';

function get<T>(url: string, config?: Parameters<typeof apiClient.get>[1]): Promise<T> {
  return apiClient.get(url, config) as unknown as Promise<T>;
}

function post<T>(url: string, data?: unknown): Promise<T> {
  return apiClient.post(url, data) as unknown as Promise<T>;
}

export const trainingApi = {
  createPlan: (employeeId: string, data: TrainingPlanRequest) =>
    post<TrainingPlanResponse>(`/training/plan/${employeeId}`, data),

  getPlan: (employeeId: string) =>
    get<TrainingPlanResponse>(`/training/plan/${employeeId}`),
};
