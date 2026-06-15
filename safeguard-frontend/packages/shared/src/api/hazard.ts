import { apiClient } from './client';
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  AlertItem,
  AlertQuery,
  PaginatedResponse,
  DashboardStats,
  TrendItem,
  HazardTypeDistribution,
} from './types';

export const hazardApi = {
  analyze: (data: AnalyzeRequest) =>
    apiClient.post<AnalyzeResponse>('/hazard/analyze', data),

  getAlerts: (params?: AlertQuery) =>
    apiClient.get<PaginatedResponse<AlertItem>>('/hazard/alerts', { params }),

  getAlert: (id: string) =>
    apiClient.get<AlertItem>(`/hazard/alerts/${id}`),

  getDashboardStats: () =>
    apiClient.get<DashboardStats>('/hazard/dashboard/stats'),

  getTrends: (days?: number) =>
    apiClient.get<TrendItem[]>('/hazard/dashboard/trends', {
      params: { days: days ?? 7 },
    }),

  getHazardDistribution: () =>
    apiClient.get<HazardTypeDistribution[]>('/hazard/dashboard/distribution'),
};
