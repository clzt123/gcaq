# SafeGuard-AI (安卫智脑) Helm Chart

> Phase 3 — K8s 生产级编排 | v0.2.0

## 🚀 快速开始

```bash
# 1. 安装
helm install safeguard-ai . \
  --namespace safeguard-ai --create-namespace \
  --set secrets.llmApiKey=sk-xxx \
  --set secrets.neo4jPassword=strong-password

# 2. 验证
kubectl get pods -n safeguard-ai
kubectl port-forward -n safeguard-ai svc/safeguard-ai-api 8000:8000
curl http://localhost:8000/health

# 3. 卸载
helm uninstall safeguard-ai -n safeguard-ai
```

## 📦 包含组件

| 组件 | K8s 资源 | 默认副本 | HPA |
|------|----------|----------|-----|
| Neo4j | Deployment + Service + PVC | 1 | — |
| Redis | Deployment + Service + PVC | 1 | — |
| Milvus | Deployment + Service + PVC | 1 | — |
| Cloud API | Deployment + Service + HPA | 2 | 2-10 |
| Edge API | Deployment + Service + HPA | 3 | 2-8 |
| Ingress | Ingress (含 TLS 支持) | — | — |

## ⚙️ 生产环境部署

```bash
# 创建生产配置
cp values.yaml values-prod.yaml
# 编辑 values-prod.yaml 填入真实密钥

# 安装
helm install safeguard-ai . \
  -f values-prod.yaml \
  --namespace safeguard-ai --create-namespace

# 启用 TLS
helm upgrade safeguard-ai . -f values-prod.yaml \
  --set ingress.tls.enabled=true \
  --set ingress.certManager=true
```
