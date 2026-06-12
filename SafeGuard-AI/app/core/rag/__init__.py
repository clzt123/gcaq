"""
GraphRAG 动态知识引擎

实现 Neo4j 图数据库的 Cypher 生成、Milvus 向量检索、
混合检索逻辑以及检索结果的上下文增强。

核心文件:
    - neo4j_client.py: Neo4j 连接管理与 Cypher 执行
    - retriever.py: 混合检索（Cypher + 向量）与兜底策略
"""
