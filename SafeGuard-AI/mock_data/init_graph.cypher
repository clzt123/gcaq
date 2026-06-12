// 1. 创建设备节点
CREATE (eq1:Equipment {name: "3号注塑机", model: "HT-250T", department: "SMT-A车间"})
CREATE (eq2:Equipment {name: "B区配电箱", model: "PD-B-04", department: "组装线-B区"})

// 2. 创建隐患/故障节点
CREATE (hz1:Hazard {name: "液压油泄漏", risk_level: "High", category: "化学品/泄漏"})
CREATE (hz2:Hazard {name: "消防通道堵塞", risk_level: "Medium", category: "消防安全"})

// 3. 创建法规/SOP节点
CREATE (reg1:Regulation {name: "《企业安全生产标准化基本规范》", clause: "5.4.2.3 危险化学品防泄漏要求"})
CREATE (sop1:SOP {name: "注塑机日常点检与泄漏应急处置SOP", doc_id: "SOP-SMT-003"})

// 4. 建立关系 (Edges)
CREATE (eq1)-[:HAS_HAZARD {frequency: "High", last_occurrence: "2024-04-15"}]->(hz1)
CREATE (eq2)-[:HAS_HAZARD {frequency: "Medium", last_occurrence: "2024-05-01"}]->(hz2)
CREATE (hz1)-[:GOVERNED_BY]->(reg1)
CREATE (hz1)-[:MITIGATED_BY]->(sop1)
CREATE (hz2)-[:GOVERNED_BY]->(reg1)

// 5. 新增隐患场景 —— 未佩戴安全帽
CREATE (eq3:Equipment {name: "2号焊接工位", model: "WLD-200S", department: "焊接车间-C区"})
CREATE (hz3:Hazard {name: "安全帽违规", risk_level: "High", category: "个人防护装备(PPE)"})
CREATE (reg3:Regulation {name: "《用人单位劳动防护用品管理规范》", clause: "第七条 头部防护"})

CREATE (eq3)-[:HAS_HAZARD {frequency: "Medium", last_occurrence: "2024-05-20"}]->(hz3)
CREATE (hz3)-[:GOVERNED_BY]->(reg3)

// 6. 新增隐患场景 —— 烟雾/火灾
CREATE (eq4:Equipment {name: "化学品仓库", model: "WH-D-01", department: "仓储部-D区"})
CREATE (hz4:Hazard {name: "初期火灾/烟雾异常", risk_level: "Critical", category: "火灾与爆炸"})
CREATE (reg4:Regulation {name: "《建筑设计防火规范》GB 50016", clause: "8.4.1 火灾自动报警系统"})
CREATE (sop4:SOP {name: "化学品泄漏与火灾应急处置SOP", doc_id: "SOP-FIRE-001"})

CREATE (eq4)-[:HAS_HAZARD {frequency: "Low", last_occurrence: "2024-05-20"}]->(hz4)
CREATE (hz4)-[:GOVERNED_BY]->(reg4)
CREATE (hz4)-[:MITIGATED_BY]->(sop4)