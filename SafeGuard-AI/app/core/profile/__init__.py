"""
员工安全画像模块 (Employee Safety Profile)

实现技术方案功能 9 — 员工安全画像：
    1. 员工违章关系图构建 (员工)-[违章]->(隐患类型)
    2. HR 系统资质同步与过期检测
    3. 员工风险等级评分算法

核心类:
    EmployeeProfile  — 员工安全档案数据模型
    RiskScorer        — 风险评分引擎
    ProfileManager    — 员工画像管理器
"""

from app.core.profile.employee import EmployeeProfile, RiskScorer, ProfileManager

__all__ = [
    "EmployeeProfile",
    "RiskScorer",
    "ProfileManager",
]
