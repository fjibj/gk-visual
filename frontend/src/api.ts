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
}

export interface TraceRelation {
  src: string
  tgt: string
  description: string
  keywords: string
  weight: number | null
  score: number | null
}

export interface HitFilterDropped {
  name: string
  score: number
  ratio: number
}

export interface HitFilter {
  top_k: number
  min_ratio: number
  core: string[]
  dropped: HitFilterDropped[]
}

export interface QueryTrace {
  entities: TraceEntity[]
  relationships: TraceRelation[]
  chunks: { content: string; chunk_id: string }[]
  hit_filter?: HitFilter
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

  deleteDocument: (docId: string) =>
    request<{ doc_id: string; status: string }>(
      `/api/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    ),

  query: (question: string) =>
    request<QueryResult>(`/api/query?question=${encodeURIComponent(question)}`),
}
