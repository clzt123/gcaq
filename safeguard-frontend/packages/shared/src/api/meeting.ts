import { apiClient } from './client';
import type { MeetingMinutesRequest, MeetingMinutesResponse } from './types';

function post<T>(url: string, data?: unknown): Promise<T> {
  return apiClient.post(url, data) as unknown as Promise<T>;
}

export const meetingApi = {
  fromAudio: (data: MeetingMinutesRequest) =>
    post<MeetingMinutesResponse>('/meeting/minutes', data),

  fromText: (data: MeetingMinutesRequest) =>
    post<MeetingMinutesResponse>('/meeting/minutes/text', data),
};
