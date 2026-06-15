import { apiClient } from './client';
import type { MeetingMinutesRequest, MeetingMinutesResponse } from './types';

export const meetingApi = {
  fromAudio: (data: MeetingMinutesRequest) =>
    apiClient.post<MeetingMinutesResponse>('/meeting/minutes', data),

  fromText: (data: MeetingMinutesRequest) =>
    apiClient.post<MeetingMinutesResponse>('/meeting/minutes/text', data),
};
