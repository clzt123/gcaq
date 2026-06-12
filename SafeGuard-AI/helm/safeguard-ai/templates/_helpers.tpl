{{/*
SafeGuard-AI — Helm 模板辅助函数
*/}}

{{/* 应用标签 */}}
{{- define "safeguard.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Neo4j 全限定名 */}}
{{- define "safeguard.neo4j.fullname" -}}
{{- printf "%s-neo4j" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Redis 全限定名 */}}
{{- define "safeguard.redis.fullname" -}}
{{- printf "%s-redis" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Milvus 全限定名 */}}
{{- define "safeguard.milvus.fullname" -}}
{{- printf "%s-milvus" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* API 全限定名 */}}
{{- define "safeguard.api.fullname" -}}
{{- printf "%s-api" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Edge 全限定名 */}}
{{- define "safeguard.edge.fullname" -}}
{{- printf "%s-edge" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
