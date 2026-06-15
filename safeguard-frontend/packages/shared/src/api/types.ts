// ===== 通用类型 =====
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ===== 用户 & 认证 =====
export type UserRole = 'inspector' | 'manager' | 'admin';

export interface User {
  id: string;
  name: string;
  phone: string;
  role: UserRole;
  department: string;
  avatar?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: User;
}

// ===== 隐患 & 告警 =====
export type RiskLevel = 'L1' | 'L2' | 'L3' | 'L4';
export type AlertSource = 'auto' | 'manual';
export type AlertStatus = 'pending' | 'processing' | 'resolved' | 'closed';

export interface AnalyzeRequest {
  image: string;        // Base64
  description?: string;
  location?: string;
}

export interface AnalyzeResponse {
  alert_id: string;
  risk_level: RiskLevel;
  hazard_type: string;
  confidence: number;
  findings: string[];
  regulation_refs: string[];
  recommended_actions: string[];
}

export interface AlertItem {
  id: string;
  created_at: string;
  source: AlertSource;
  hazard_type: string;
  location: string;
  risk_level: RiskLevel;
  status: AlertStatus;
  description: string;
  image_url?: string;
  reported_by?: string;
}

export interface AlertQuery {
  risk_level?: RiskLevel;
  source?: AlertSource;
  status?: AlertStatus;
  search?: string;
  page?: number;
  page_size?: number;
}

// ===== 工单 =====
export type TicketStatus = 'pending' | 'assigned' | 'in_progress' | 'completed' | 'closed';

export interface TicketItem {
  id: string;
  alert_id: string;
  title: string;
  hazard_type: string;
  risk_level: RiskLevel;
  status: TicketStatus;
  assigned_to?: string;
  created_at: string;
  due_date?: string;
  location: string;
}

// ===== 仪表盘 =====
export interface DashboardStats {
  today_hazards: number;
  yesterday_hazards: number;
  pending_tickets: number;
  overdue_tickets: number;
  monthly_resolution_rate: number;
  last_month_resolution_rate: number;
  online_inspectors: number;
  total_inspectors: number;
}

export interface TrendItem {
  date: string;
  count: number;
  risk_level: RiskLevel;
}

export interface HazardTypeDistribution {
  hazard_type: string;
  count: number;
}

// ===== 会议 & 培训 =====
export interface MeetingMinutesRequest {
  audio_url?: string;
  text?: string;
}

export interface MeetingMinutesResponse {
  title: string;
  date: string;
  attendees: string[];
  summary: string;
  action_items: string[];
  key_decisions: string[];
}

export interface TrainingPlanRequest {
  employee_id: string;
}

export interface TrainingPlanResponse {
  employee_id: string;
  recommended_courses: Array<{
    course_id: string;
    title: string;
    reason: string;
    priority: 'high' | 'medium' | 'low';
  }>;
}
