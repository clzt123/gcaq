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

// Wrapper to let TypeScript know the response interceptor unwraps res.data
function get<T>(url: string, config?: Parameters<typeof apiClient.get>[1]): Promise<T> {
  return apiClient.get(url, config) as unknown as Promise<T>;
}

function post<T>(url: string, data?: unknown): Promise<T> {
  return apiClient.post(url, data) as unknown as Promise<T>;
}

export const hazardApi = {
  analyze: (data: AnalyzeRequest) =>
    post<AnalyzeResponse>('/hazard/analyze', data),

  getAlerts: (params?: AlertQuery) =>
    get<PaginatedResponse<AlertItem>>('/hazard/alerts', { params }),

  getAlert: (id: string) =>
    get<AlertItem>(`/hazard/alerts/${id}`),

  getDashboardStats: () =>
    get<DashboardStats>('/hazard/dashboard/stats'),

  getTrends: (days?: number) =>
    get<TrendItem[]>('/hazard/dashboard/trends', {
      params: { days: days ?? 7 },
    }),

  getHazardDistribution: () =>
    get<HazardTypeDistribution[]>('/hazard/dashboard/distribution'),
};
