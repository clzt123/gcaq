/**
 * Vite plugin: mock all APIs for development without backend.
 * Username determines role: admin* → admin, manager* → manager, else → inspector
 */
import type { Plugin } from 'vite';

const mockUsers: Record<string, { name: string; role: string }> = {
  admin:     { name: '李管理', role: 'admin' },
  manager:   { name: '张主管', role: 'manager' },
  inspector: { name: '王巡检', role: 'inspector' },
};

function detectRole(username: string): string {
  if (username.startsWith('admin')) return 'admin';
  if (username.startsWith('manager') || username.startsWith('mgr')) return 'manager';
  return 'inspector';
}

function json(res: any, data: any, code = 200) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(data));
}

function readBody(req: any): Promise<string> {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', (chunk: Buffer) => (body += chunk.toString()));
    req.on('end', () => resolve(body));
  });
}

// ===== Mock Data =====

function mockKnowledgeDocs() {
  return { items: [
    { id: 'k1', title: '高处作业安全操作规程', category: 'sop', content: '1. 凡在坠落高度基准面2米及以上有可能坠落的高处进行作业，均称为高处作业。\n2. 高处作业人员必须经体检合格，凡患有高血压、心脏病、癫痫病、精神病、严重贫血等禁忌症的人员，不得从事高处作业。\n3. 高处作业必须正确佩戴安全带，安全带应高挂低用，挂在牢固可靠处。\n4. 高处作业下方应设置警戒区，安排专人监护，严禁无关人员进入。\n5. 六级以上大风、大雨、大雪、大雾等恶劣天气，禁止露天高处作业。', tags: ['高处作业', '安全带', '操作规程', '风险L1'], updated_at: '2026-05-15', related_count: 3 },
    { id: 'k2', title: '安全生产法（2025修订）第28条', category: 'regulation', content: '生产经营单位应当对从业人员进行安全生产教育和培训，保证从业人员具备必要的安全生产知识，熟悉有关的安全生产规章制度和安全操作规程，掌握本岗位的安全操作技能，了解事故应急处理措施，知悉自身在安全生产方面的权利和义务。未经安全生产教育和培训合格的从业人员，不得上岗作业。', tags: ['安全生产法', '培训', '法规'], updated_at: '2025-12-01', related_count: 5 },
    { id: 'k3', title: '便携式气体检测仪操作手册', category: 'manual', content: '一、开机前检查\n1. 检查电池电量是否充足\n2. 检查传感器进气口是否通畅\n3. 确认设备在校准有效期内（6个月）\n\n二、操作步骤\n1. 在清洁空气中开机，等待自检完成（约30秒）\n2. 确认零点校准正常\n3. 进入检测区域前进行功能测试\n4. 检测时将探头置于呼吸带高度\n5. 读数稳定后记录数据\n\n三、报警响应\n- 一级报警（25%LEL）：立即撤离\n- 二级报警（50%LEL）：紧急疏散\n\n四、维护保养\n- 每次使用后用干布清洁\n- 每月进行一次通气测试\n- 每6个月送检校准', tags: ['气体检测', '设备手册', '操作规程'], updated_at: '2026-04-20', related_count: 2 },
    { id: 'k4', title: '化学品储存安全规范', category: 'regulation', content: '危险化学品应当储存在专用仓库、专用场地或者专用储存室内，并由专人负责管理。剧毒化学品以及储存数量构成重大危险源的其他危险化学品，应当在专用仓库内单独存放，并实行双人收发、双人保管制度。', tags: ['化学品', '储存', '法规', '风险L1'], updated_at: '2026-03-10', related_count: 4 },
    { id: 'k5', title: '消防器材日常检查SOP', category: 'sop', content: '1. 灭火器检查：\n- 压力表指针在绿色区域\n- 瓶体无锈蚀、变形\n- 喷管无堵塞\n- 每月记录一次\n\n2. 消火栓检查：\n- 阀门启闭正常\n- 水带无破损\n- 接口密封完好\n- 每季度放水测试\n\n3. 应急照明检查：\n- 每月测试一次断电点亮\n- 蓄电池每年更换', tags: ['消防', '检查', 'SOP', '月度'], updated_at: '2026-06-01', related_count: 2 },
    { id: 'k6', title: '电动叉车安全操作手册', category: 'manual', content: '叉车操作人员必须持证上岗。作业前应检查制动、转向、液压系统。载货行驶时货叉应离地300-400mm。严禁载人、超载、超速。坡道行驶时货物应朝向上坡方向。', tags: ['叉车', '设备', '操作手册'], updated_at: '2026-02-18', related_count: 1 },
  ]};
}

function mockTrainingCourses() {
  return { items: [
    { id: 'c1', title: '高处作业安全培训', category: '特种作业', duration: '4小时', required_for: ['维修工', '电焊工', '架子工'], completed_count: 18, total_count: 25, priority: 'high' },
    { id: 'c2', title: '化学品安全与MSDS解读', category: '危化品', duration: '2小时', required_for: ['化学品管理员', '实验室人员', '仓库管理员'], completed_count: 10, total_count: 12, priority: 'high' },
    { id: 'c3', title: '消防应急演练', category: '应急', duration: '2小时', required_for: ['全体员工'], completed_count: 45, total_count: 50, priority: 'medium' },
    { id: 'c4', title: 'PPE个人防护装备使用', category: '基础安全', duration: '1小时', required_for: ['全体员工'], completed_count: 40, total_count: 50, priority: 'medium' },
    { id: 'c5', title: '新员工入职安全培训', category: '入职', duration: '8小时', required_for: ['新员工'], completed_count: 5, total_count: 8, priority: 'low' },
  ]};
}

function mockTrainingRecords() {
  return { items: [
    { id: 'r1', employee_name: '王巡检', course_title: '高处作业安全培训', status: 'completed', score: 92, assigned_date: '2026-05-10', completed_date: '2026-05-12' },
    { id: 'r2', employee_name: '赵工', course_title: '化学品安全与MSDS解读', status: 'in_progress', assigned_date: '2026-06-01', completed_date: null },
    { id: 'r3', employee_name: '钱师傅', course_title: '消防应急演练', status: 'completed', score: 88, assigned_date: '2026-04-15', completed_date: '2026-04-15' },
    { id: 'r4', employee_name: '孙巡检', course_title: 'PPE个人防护装备使用', status: 'overdue', assigned_date: '2026-05-01', completed_date: null },
    { id: 'r5', employee_name: '李工', course_title: '高处作业安全培训', status: 'assigned', assigned_date: '2026-06-10', completed_date: null },
  ]};
}

function mockEmployees() {
  return { items: [
    { id: 'emp-001', name: '王巡检', department: '一车间', role: '巡检员', violation_count: 0, training_completion: 92, risk_score: 15, last_patrol: '2026-06-15' },
    { id: 'emp-002', name: '赵工', department: '二车间', role: '操作工', violation_count: 3, training_completion: 60, risk_score: 72, last_patrol: '2026-06-10' },
    { id: 'emp-003', name: '钱师傅', department: '仓库', role: '仓库管理员', violation_count: 1, training_completion: 85, risk_score: 35, last_patrol: '2026-06-14' },
    { id: 'emp-004', name: '孙巡检', department: '一车间', role: '巡检员', violation_count: 0, training_completion: 100, risk_score: 8, last_patrol: '2026-06-15' },
    { id: 'emp-005', name: '李工', department: '二车间', role: '维修工', violation_count: 4, training_completion: 45, risk_score: 85, last_patrol: '2026-06-08' },
    { id: 'emp-006', name: '周安全', department: 'EHS管理部', role: '安全员', violation_count: 0, training_completion: 100, risk_score: 5, last_patrol: '2026-06-15' },
  ]};
}

function mockEmployeeDetail() {
  return { data: { id: 'emp-001', name: '王巡检', department: '一车间', role: '巡检员', phone: '13800138001', violation_count: 0, training_completion: 92, risk_score: 15 }};
}

function mockViolations() {
  return { items: [
    { id: 'v1', date: '2026-06-10', type: '安全帽佩戴不规范', level: 'L2', status: '已整改' },
    { id: 'v2', date: '2026-05-22', type: '未在规定通道行走', level: 'L3', status: '已整改' },
  ]};
}

function mockEmpTrainings() {
  return { items: [
    { id: 'et1', course: '高处作业安全培训', status: 'completed', score: 92, date: '2026-05-12' },
    { id: 'et2', course: '消防应急演练', status: 'completed', score: 88, date: '2026-04-15' },
    { id: 'et3', course: 'PPE个人防护装备使用', status: 'completed', score: 95, date: '2026-03-20' },
  ]};
}

function mockHealth() {
  return { services: [
    { name: 'FastAPI 网关', status: 'healthy', latency_ms: 12, uptime: '15天 3小时' },
    { name: 'Neo4j 图数据库', status: 'healthy', latency_ms: 34, uptime: '15天 3小时' },
    { name: 'Milvus 向量库', status: 'healthy', latency_ms: 45, uptime: '15天 3小时' },
    { name: 'Redis 缓存', status: 'degraded', latency_ms: 120, uptime: '3天 7小时' },
    { name: 'Qwen-VL 视觉服务', status: 'healthy', latency_ms: 230, uptime: '15天 3小时' },
    { name: 'MCP 工具链', status: 'healthy', latency_ms: 18, uptime: '15天 3小时' },
  ]};
}

function mockEdgeNodes() {
  return { nodes: [
    { id: 'edge-01', name: '一车间边缘节点', location: 'A栋1层', status: 'online', last_heartbeat: '2秒前', queue_size: 0 },
    { id: 'edge-02', name: '二车间边缘节点', location: 'B栋1层', status: 'online', last_heartbeat: '5秒前', queue_size: 3 },
    { id: 'edge-03', name: '仓库边缘节点', location: 'C栋仓库区', status: 'offline', last_heartbeat: '2小时前', queue_size: 17 },
  ]};
}

function mockAuditLogs() {
  return { items: [
    { id: 'log1', user: '李管理', action: '创建用户', target: '赵工 (emp-002)', detail: '创建了巡检员账号', ip: '192.168.1.100', timestamp: '2026-06-15 14:30:22' },
    { id: 'log2', user: '张主管', action: '审核告警', target: '告警 #ALT-2026-0042', detail: '确认安全帽缺失告警，创建工单', ip: '192.168.1.101', timestamp: '2026-06-15 14:15:08' },
    { id: 'log3', user: '王巡检', action: '登录', target: '系统', detail: '通过 PWA 移动端登录', ip: '192.168.110.50', timestamp: '2026-06-15 14:00:01' },
    { id: 'log4', user: '张主管', action: '编辑工单', target: '工单 #TKT-2026-0089', detail: '将工单分配给王巡检', ip: '192.168.1.101', timestamp: '2026-06-15 13:45:33' },
    { id: 'log5', user: '李管理', action: '删除文档', target: '旧版消防SOP', detail: '删除已废弃的消防检查SOP v1.0', ip: '192.168.1.100', timestamp: '2026-06-15 11:20:15' },
    { id: 'log6', user: '系统', action: '自动检测', target: 'A车间-3号产线', detail: '摄像头检测到安全帽缺失，自动创建告警', ip: '-', timestamp: '2026-06-15 10:05:00' },
    { id: 'log7', user: '王巡检', action: '上报隐患', target: 'B车间-化学品区', detail: '人工拍照上报油污泄漏', ip: '192.168.110.50', timestamp: '2026-06-15 09:30:45' },
    { id: 'log8', user: '张主管', action: '登录', target: '系统', detail: '通过桌面端登录', ip: '192.168.1.101', timestamp: '2026-06-15 08:55:00' },
  ]};
}

function mockTickets() {
  return { items: [
    { id: 't1', alert_id: 'a1', title: '安全帽缺失-A车间3号产线', hazard_type: '安全帽缺失', risk_level: 'L1', status: 'pending', assigned_to: null, created_at: '2026-06-15 10:05', due_date: '2026-06-16', location: 'A车间-3号产线' },
    { id: 't2', alert_id: 'a2', title: '油污泄漏-B车间化学品区', hazard_type: '油污泄漏', risk_level: 'L2', status: 'in_progress', assigned_to: '王巡检', created_at: '2026-06-15 09:30', due_date: '2026-06-15', location: 'B车间-化学品区' },
    { id: 't3', alert_id: 'a3', title: '通道堵塞-仓库东区出口', hazard_type: '通道堵塞', risk_level: 'L2', status: 'assigned', assigned_to: '赵工', created_at: '2026-06-14 15:20', due_date: '2026-06-16', location: '仓库-东区出口' },
    { id: 't4', alert_id: 'a4', title: '消防器材过期-C车间', hazard_type: '消防器材过期', risk_level: 'L3', status: 'completed', assigned_to: '孙巡检', created_at: '2026-06-13 08:00', due_date: '2026-06-14', location: 'C车间-焊接区' },
  ]};
}

// ===== Plugin =====

export function mockApiPlugin(): Plugin {
  return {
    name: 'safeguard-mock-api',
    configureServer(server) {

      // Auth
      server.middlewares.use('/api/v1/auth/login', async (req, res) => {
        if (req.method !== 'POST') { json(res, { detail: 'Method Not Allowed' }, 405); return; }
        const body = await readBody(req);
        try {
          const { username } = JSON.parse(body);
          const role = detectRole(username ?? '');
          const u = mockUsers[role];
          json(res, { token: `mock-jwt-${role}-dev`, user: { id: `mock-${role}-001`, name: u.name, phone: '13800138000', role, department: role === 'inspector' ? '一车间' : 'EHS管理部' }});
        } catch { json(res, { detail: 'Invalid JSON' }, 400); }
      });

      // Knowledge
      server.middlewares.use('/api/v1/knowledge/search', (_req, res) => json(res, mockKnowledgeDocs()));
      server.middlewares.use(/^\/api\/v1\/knowledge\/docs\/(.+)/, (_req, res) => {
        const docs = mockKnowledgeDocs().items;
        const id = (_req as any).url?.split('/').pop();
        const doc = docs.find((d: any) => d.id === id) || docs[0];
        json(res, doc);
      });

      // Training
      server.middlewares.use('/api/v1/training/courses', (_req, res) => json(res, mockTrainingCourses()));
      server.middlewares.use('/api/v1/training/records', (_req, res) => json(res, mockTrainingRecords()));

      // Employees
      server.middlewares.use('/api/v1/employees', (_req, res) => {
        const url = (_req as any).url ?? '';
        if (url.includes('/violations')) return json(res, mockViolations());
        if (url.includes('/trainings')) return json(res, mockEmpTrainings());
        if (url.match(/\/employees\/\w+$/)) return json(res, mockEmployeeDetail());
        json(res, mockEmployees());
      });

      // Users
      server.middlewares.use('/api/v1/users', (_req, res) => {
        if (_req.method === 'POST') return json(res, { id: 'emp-new', name: '新用户', role: 'inspector' }, 201);
        json(res, mockEmployees());
      });

      // System
      server.middlewares.use('/api/v1/system/health', (_req, res) => json(res, mockHealth()));
      server.middlewares.use('/api/v1/system/edge-nodes', (_req, res) => json(res, mockEdgeNodes()));
      server.middlewares.use('/api/v1/system/audit-logs', (_req, res) => json(res, mockAuditLogs()));

      // Tickets
      server.middlewares.use('/api/v1/tickets/my', (_req, res) => json(res, mockTickets()));
      server.middlewares.use('/api/v1/tickets', (_req, res) => {
        const url = (_req as any).url ?? '';
        if (url.match(/\/tickets\/\w+$/) && url !== '/api/v1/tickets' && !url.includes('my')) {
          const t = mockTickets().items[0];
          return json(res, { data: t });
        }
        json(res, mockTickets());
      });

      // Dashboard
      server.middlewares.use('/api/v1/hazard/dashboard/stats', (_req, res) => json(res, {
        today_hazards: 12, yesterday_hazards: 9, pending_tickets: 8, overdue_tickets: 3,
        monthly_resolution_rate: 94, last_month_resolution_rate: 92,
        online_inspectors: 24, total_inspectors: 31,
      }));
      server.middlewares.use('/api/v1/hazard/dashboard/trends', (_req, res) => json(res, [
        { date: '2026-06-09', count: 8, risk_level: 'L2' }, { date: '2026-06-10', count: 12, risk_level: 'L1' },
        { date: '2026-06-11', count: 6, risk_level: 'L2' }, { date: '2026-06-12', count: 15, risk_level: 'L1' },
        { date: '2026-06-13', count: 10, risk_level: 'L2' }, { date: '2026-06-14', count: 5, risk_level: 'L3' },
        { date: '2026-06-15', count: 4, risk_level: 'L3' },
      ]));
      server.middlewares.use('/api/v1/hazard/dashboard/distribution', (_req, res) => json(res, [
        { hazard_type: '安全帽缺失', count: 5 }, { hazard_type: '通道堵塞', count: 3 },
        { hazard_type: '化学品泄漏', count: 2 }, { hazard_type: '烟雾/火情', count: 1 },
        { hazard_type: '油污泄漏', count: 1 },
      ]));
      server.middlewares.use('/api/v1/hazard/alerts', (_req, res) => json(res, { items: [
        { id: 'a1', created_at: '2026-06-15 14:32', source: 'auto', hazard_type: '安全帽缺失', location: 'A车间-3号产线', risk_level: 'L1', status: 'pending', description: '监控摄像头检测到工人未佩戴安全帽', reported_by: '系统自动' },
        { id: 'a2', created_at: '2026-06-15 13:15', source: 'manual', hazard_type: '油污泄漏', location: 'B车间-化学品区', risk_level: 'L2', status: 'processing', description: '巡检员发现地面有油污', reported_by: '王巡检' },
        { id: 'a3', created_at: '2026-06-15 11:08', source: 'auto', hazard_type: '通道堵塞', location: '仓库-东区出口', risk_level: 'L2', status: 'processing', description: '货物堆放在消防通道', reported_by: '系统自动' },
        { id: 'a4', created_at: '2026-06-15 09:45', source: 'auto', hazard_type: '烟雾告警', location: 'C车间-焊接区', risk_level: 'L3', status: 'resolved', description: '焊接烟雾触发传感器', reported_by: '系统自动' },
      ], total: 4, page: 1, page_size: 20 }));
    },
  };
}
