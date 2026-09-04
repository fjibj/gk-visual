export interface GraphNode {
  id: string
  type: string
  description: string
}

export interface GraphEdge {
  source: string
  target: string
  description: string
  keywords: string
  weight: number | null
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface DocumentInfo {
  doc_id: string
  title: string
  content_length: number
  entity_count: number
  relation_count: number
}

export interface TraceEntity {
  name: string
  type: string
  description: string
  score: number | null
  /** 证据层：anchor=问题里点名的锚点，cited=答案里字面引用的，path=连接两者的路径点 */
  layer?: 'anchor' | 'cited' | 'path' | null
}

export interface TraceRelation {
  src: string
  tgt: string
  description: string
  keywords: string
  weight: number | null
  score: number | null
  /** direct=两端都是锚点/引用点（边本身就是证据），path=靠它中间才连上 */
  layer?: 'direct' | 'path' | null
}

export interface HitPath {
  from: string
  to: string
  kind: string
  hops: number
  paths: string[][]
}

export interface HitRecallItem {
  name: string
  score: number | null
}

export interface HitLayers {
  anchor_mode: 'literal' | 'vector_fallback' | 'no_anchor' | 'vdb_error' | 'none'
  anchors: string[]
  cited: string[]
  paths: HitPath[]
  disconnected: { a: string; b: string | null; kind: string }[]
  recall_only: HitRecallItem[]
  /** 问题抽出的低层关键词里，图上查无此名的（文档没写过 / 实体未对齐） */
  unmatched_keywords?: string[]
  top_k: number
  max_hops: number
  max_paths: number
}

export interface RetrievedInfo {
  entity_count: number
  relation_count: number
  entities: string[]
  relationships: string[]
}

export interface QueryTrace {
  entities: TraceEntity[]
  relationships: TraceRelation[]
  chunks: { content: string; chunk_id: string }[]
  /** 检索器捞到的原记录，不受高亮分层影响 */
  retrieved?: RetrievedInfo
  hit_layers?: HitLayers
}

export interface QueryResult {
  answer: string
  trace: QueryTrace
  trace_hit: boolean
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body && body.detail) detail = String(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  getGraph: () => request<GraphData>('/api/graph'),

  createEntity: (name: string, type: string, description: string) =>
    request('/api/entities', json('POST', { name, type: type || null, description: description || null })),

  editEntity: (name: string, type: string, description: string) =>
    request(`/api/entities/${encodeURIComponent(name)}`, json('PATCH', { type: type || null, description: description || null })),

  deleteEntity: (name: string) =>
    request(`/api/entities/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  createRelation: (source: string, target: string, description: string, keywords: string) =>
    request('/api/relations', json('POST', { source, target, description: description || null, keywords: keywords || null })),

  editRelation: (source: string, target: string, description: string, keywords: string) =>
    request('/api/relations', json('PATCH', { source, target, description: description || null, keywords: keywords || null })),

  deleteRelation: (source: string, target: string) =>
    request(
      `/api/relations?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`,
      { method: 'DELETE' },
    ),

  merge: (sources: string[], target: string) =>
    request<{
      target: string
      deleted: string[]
      relationships_transferred: number
      sources_remaining: string[]
    }>('/api/merge', json('POST', { sources, target })),

  listDocuments: () => request<{ documents: DocumentInfo[] }>('/api/documents'),

  uploadDocument: (title: string, content: string) =>
    request<{
      doc_id: string
      created: boolean
      entity_count: number
      relation_count: number
    }>('/api/documents', json('POST', { title, content })),

  /** 真实文件上传：浏览器拼 multipart，后端解析成纯文本后走 S6 覆盖更新 */
  uploadFile: (title: string | null, file: File) => {
    const fd = new FormData()
    if (title) fd.append('title', title)
    fd.append('file', file, file.name)
    return request<{
      doc_id: string
      title: string
      chars: number
      created: boolean
      entity_count: number
      relation_count: number
    }>('/api/documents/upload', { method: 'POST', body: fd })
  },

  deleteDocument: (docId: string) =>
    request<{ doc_id: string; status: string }>(
      `/api/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    ),

  query: (question: string) =>
    request<QueryResult>(`/api/query?question=${encodeURIComponent(question)}`),
}
