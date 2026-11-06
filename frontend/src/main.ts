import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'
import './style.css'
import { api, GraphData, DocumentInfo, HitLayers, RetrievedInfo, Origin, Provenance } from './api'

cytoscape.use(coseBilkent)

const TYPE_COLORS: Record<string, string> = {
  person: '#ff9f43',
  organization: '#54a0ff',
  location: '#1dd1a1',
  concept: '#a55eea',
  other: '#c8ced6',
}

function typeColor(t: string): string {
  return TYPE_COLORS[t] || TYPE_COLORS.other
}

// 检索高亮的通道分配（2026-08-30 重做，替掉「浅红→浅粉」明度阶梯）：
//   证据层 → 形态：粗实环＝问题锚点，虚线环＝答案引用 / 路径
//   轮次   → 色温：本轮暖红，更早冷灰蓝（人眼判色温可靠，判三种浅粉不可靠）
//   第几轮 → 标签角标 ¹²³ + 图例文字
// 旧实现用元素 opacity 逐轮洗淡，连标签和类型色一起看不清了；现在不再淡化元素本身。
const ROUND_COLORS = ['#c81e2e', '#5b6b82']
const ROUND_SUP = ['', '¹', '²', '³']

interface RingSpec {
  width: number
  style: 'solid' | 'dashed'
  size: number
}

const RINGS: Record<string, RingSpec> = {
  anchor: { width: 4.5, style: 'solid', size: 40 },
  cited: { width: 2.5, style: 'dashed', size: 34 },
  path: { width: 2, style: 'dashed', size: 32 },
}

function roundColor(age: number): string {
  return age > 0 ? ROUND_COLORS[1] : ROUND_COLORS[0]
}

function roundSup(age: number): string {
  return ROUND_SUP[Math.min(Math.max(Math.floor(age) || 0, 0), ROUND_SUP.length - 1)] || ''
}

function ringOf(ele: any): RingSpec {
  const base = RINGS[String(ele.data('hitLayer'))] || RINGS.cited
  if (Number(ele.data('hitAge')) > 0) {
    // 更早的轮次只减一档粗细，形态不变——「它是锚点」不该随时间丢失
    return { width: Math.max(1.5, base.width - 1), style: base.style, size: base.size - 2 }
  }
  return base
}

const MANUAL_COLOR = '#8250df'

/** 「这条是怎么来的」→ 一句人话。四态与后端 provenance.ORIGIN_* 一一对应。 */
function originLabel(origin?: string): string {
  switch (origin) {
    case 'manual':
      return '人工创建'
    case 'mixed':
      return '文档抽取 + 人工改动'
    case 'extracted':
      return '文档抽取'
    default:
      return '来源未知（库里没有来源记录）'
  }
}

function isManual(origin?: string): boolean {
  return origin === 'manual' || origin === 'mixed'
}

function provenanceHtml(origin?: Origin, prov?: Provenance): string {
  const p = prov || { manual: false, docs: [], doc_ids: [], chunks: 0, unresolved: 0 }
  const parts: string[] = [`<div class="prov-origin">${escapeHtml(originLabel(origin))}</div>`]
  if (p.docs.length) {
    const docs = p.docs.map((d) => escapeHtml(d)).join('、')
    parts.push(`<div class="prov-docs">来源文档：${docs}（${p.chunks} 块）</div>`)
  } else if (p.manual) {
    parts.push('<div class="prov-docs">没有关联文档：内容是人直接写进图的</div>')
  } else if (p.chunks === 0) {
    parts.push('<div class="prov-docs">库里的记录没有保留来源</div>')
  }
  if (p.unresolved > 0) {
    parts.push(
      `<div class="prov-warn">另有 ${p.unresolved} 块内容已无据可查（所属文档被覆盖或删除）</div>`,
    )
  }
  return `<label>来源</label><div class="prov-box">${parts.join('')}</div>`
}

const cy = cytoscape({
  container: document.getElementById('cy')!,
  style: [
    {
      selector: 'node',
      style: {
        label: (ele: any) =>
          `${ele.data('id')}${ele.data('manualMark') || ''}${ele.data('hitSup') || ''}`,
        'background-color': (ele) => typeColor(String(ele.data('type'))),
        color: '#1f2328',
        'text-valign': 'bottom',
        'text-halign': 'center',
        'font-size': '11',
        'text-margin-y': 4,
        width: '32',
        height: '32',
        'text-wrap': 'wrap',
        'text-max-width': '80',
      },
    },
    {
      selector: 'edge',
      style: {
        width: '1.5',
        'line-color': '#c8ced6',
        'target-arrow-color': '#c8ced6',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        label: (ele: any) =>
          ele.hasClass('edge-hover') || ele.selected() ? String(ele.data('description')) : '',
        'font-size': '9',
        color: '#57606a',
        'text-rotation': 'autorotate',
        'text-background-color': '#ffffff',
        'text-background-opacity': 0.95,
        'text-background-padding': '2',
        'text-wrap': 'wrap',
        'text-max-width': '90',
      },
    },
    {
      selector: 'edge.edge-hover',
      style: {
        width: '2.5',
        'line-color': '#1f6feb',
        'target-arrow-color': '#1f6feb',
      },
    },
    {
      selector: ':selected',
      style: {
        'border-width': '3',
        'border-color': '#1f6feb',
        'line-color': '#1f6feb',
        'target-arrow-color': '#1f6feb',
      },
    },
    {
      selector: '.dimmed',
      style: {
        opacity: 0.2,
      },
    },
    {
      selector: 'node.manual',
      style: {
        // 人工味儿用「底晕」而不是边框：边框通道已经被检索分层占用了（实线=锚点/虚线=引用）
        'underlay-color': MANUAL_COLOR,
        'underlay-opacity': 0.16,
        'underlay-padding': 5,
        'underlay-shape': 'ellipse',
      },
    },
    {
      selector: 'edge.manual',
      style: {
        'underlay-color': MANUAL_COLOR,
        'underlay-opacity': 0.22,
        'underlay-padding': 3,
      },
    },
    {
      selector: 'node.hit',
      style: {
        'border-width': (ele: any) => ringOf(ele).width,
        'border-color': (ele: any) => roundColor(ele.data('hitAge')),
        'border-style': (ele: any) => ringOf(ele).style,
        'border-dash-pattern': [4, 2.5],
        width: (ele: any) => ringOf(ele).size,
        height: (ele: any) => ringOf(ele).size,
        'font-weight': (ele: any) => (ele.data('hitLayer') === 'anchor' ? 'bold' : 'normal'),
      },
    },
    {
      selector: 'edge.hit',
      style: {
        width: (ele: any) => (Number(ele.data('hitAge')) > 0 ? 1.8 : 2.6),
        'line-color': (ele: any) => roundColor(ele.data('hitAge')),
        'target-arrow-color': (ele: any) => roundColor(ele.data('hitAge')),
        'line-style': (ele: any) => (ele.data('hitLayer') === 'path' ? 'dashed' : 'solid'),
      },
    },
  ],
  layout: {
    name: 'cose-bilkent',
    nodeRepulsion: 8000,
    idealEdgeLength: 120,
    edgeElasticity: 0.45,
    gravity: 0.25,
    numIter: 2500,
    tile: true,
    padding: 50,
  } as any,
})

;(window as any).__gkb_cy__ = cy

let currentData: GraphData = { nodes: [], edges: [] }
const queryRounds: { entities: Map<string, string>; relationships: Map<string, string> }[] = []

function setStatus(msg: string, isError = false) {
  const el = document.getElementById('status')!
  el.textContent = msg
  el.style.color = isError ? '#ff7b72' : '#8b949e'
}

async function loadGraph() {
  try {
    const data = await api.getGraph()
    currentData = data
    renderGraph(data)
    setStatus(`已加载 ${data.nodes.length} 实体 · ${data.edges.length} 关系`)
  } catch (err) {
    setStatus(`加载失败: ${(err as Error).message}`, true)
  }
}

function renderGraph(data: GraphData) {
  const nodes = data.nodes.map((n) => ({
    data: {
      id: n.id,
      type: n.type,
      description: n.description,
      origin: n.origin || 'unknown',
      manualMark: isManual(n.origin) ? ' ✎' : '',
    },
    classes: isManual(n.origin) ? 'manual' : '',
  }))
  const edges = data.edges.map((e, i) => ({
    data: {
      id: `e${i}:${e.source}:${e.target}`,
      source: e.source,
      target: e.target,
      description: e.description,
      keywords: e.keywords,
      origin: e.origin || 'unknown',
    },
    classes: isManual(e.origin) ? 'manual' : '',
  }))
  cy.elements().remove()
  cy.add(nodes)
  cy.add(edges)
  cy.layout({
    name: 'cose-bilkent',
    nodeRepulsion: 8000,
    idealEdgeLength: 120,
    edgeElasticity: 0.45,
    gravity: 0.25,
    numIter: 2500,
    tile: true,
    padding: 50,
  } as any).run()
  if (queryRounds.length > 0) renderQueryHighlight()
  renderProvLegend()
}

/** ✎ 图例：图里有人工痕迹时才出现，不占无谓的版面 */
function renderProvLegend() {
  const el = document.getElementById('prov-legend')
  if (!el) return
  const hasManual = cy.elements('.manual').length > 0
  if (!hasManual) {
    el.classList.add('hidden')
    el.innerHTML = ''
    return
  }
  el.innerHTML =
    `<div class="lg-row"><span class="lg-mark" style="color:${MANUAL_COLOR}">✎</span>` +
    `人工创建 / 改过（紫色底晕）</div>`
  el.classList.remove('hidden')
}

// ---- 详情面板 ----

const panel = document.getElementById('panel')!
const panelTitle = document.getElementById('panel-title')!
const panelForm = document.getElementById('panel-form')!
const panelActions = document.getElementById('panel-actions')!

type Mode = 'node' | 'edge' | 'new-entity' | 'new-relation' | 'merge' | 'documents'
let mode: Mode | null = null
let selectedNodeId = ''
let selectedEdge: { source: string; target: string } | null = null

function hidePanel() {
  panel.classList.add('hidden')
  mode = null
  selectedNodeId = ''
  selectedEdge = null
  cy.elements().unselect()
  cy.elements().removeClass('dimmed')
}

function highlightNeighbors(ele: any) {
  cy.elements().removeClass('dimmed')
  const neighborhood = ele.closedNeighborhood()
  cy.elements().difference(neighborhood).addClass('dimmed')
}

function showPanel(title: string, formHtml: string, actionsHtml: string) {
  panelTitle.textContent = title
  panelForm.innerHTML = formHtml
  panelActions.innerHTML = actionsHtml
  panel.classList.remove('hidden')
}

function entityOptions(selected?: string): string {
  return currentData.nodes
    .map(
      (n) =>
        `<option value="${escapeHtml(n.id)}" ${n.id === selected ? 'selected' : ''}>${escapeHtml(n.id)}</option>`,
    )
    .join('')
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// ---- 选中节点/边 → 编辑面板 ----

function showNodePanel(id: string) {
  const node = currentData.nodes.find((n) => n.id === id)
  if (!node) return
  mode = 'node'
  selectedNodeId = id
  showPanel(
    `实体：${id}`,
    `
      ${provenanceHtml(node.origin, node.provenance)}
      <label>类型</label>
      <input id="f-type" value="${escapeHtml(node.type)}" />
      <label>描述</label>
      <textarea id="f-desc">${escapeHtml(node.description)}</textarea>
    `,
    `
      <div class="row">
        <button class="primary" id="a-save">保存</button>
        <button class="danger" id="a-delete">删除</button>
      </div>
    `,
  )
  document.getElementById('a-save')!.onclick = saveEntity
  document.getElementById('a-delete')!.onclick = deleteEntity
}

function showEdgePanel(source: string, target: string) {
  const edge = currentData.edges.find((e) => e.source === source && e.target === target)
  if (!edge) return
  mode = 'edge'
  selectedEdge = { source, target }
  showPanel(
    `关系：${source} → ${target}`,
    `
      ${provenanceHtml(edge.origin, edge.provenance)}
      <label>描述</label>
      <textarea id="f-desc">${escapeHtml(edge.description)}</textarea>
      <label>关键词</label>
      <input id="f-keywords" value="${escapeHtml(edge.keywords)}" />
    `,
    `
      <div class="row">
        <button class="primary" id="a-save">保存</button>
        <button class="danger" id="a-delete">删除</button>
      </div>
    `,
  )
  document.getElementById('a-save')!.onclick = saveRelation
  document.getElementById('a-delete')!.onclick = deleteRelation
}

// ---- 新建/合并表单 ----

function showNewEntityPanel() {
  mode = 'new-entity'
  showPanel(
    '新建实体',
    `
      <label>名称</label>
      <input id="f-name" />
      <label>类型</label>
      <input id="f-type" />
      <label>描述</label>
      <textarea id="f-desc"></textarea>
    `,
    `<div class="row"><button class="primary" id="a-create">创建</button></div>`,
  )
  document.getElementById('a-create')!.onclick = createEntity
}

function showNewRelationPanel() {
  mode = 'new-relation'
  showPanel(
    '新建关系',
    `
      <label>源实体</label>
      <select id="f-source">${entityOptions()}</select>
      <label>目标实体</label>
      <select id="f-target">${entityOptions()}</select>
      <label>描述</label>
      <textarea id="f-desc"></textarea>
      <label>关键词</label>
      <input id="f-keywords" />
    `,
    `<div class="row"><button class="primary" id="a-create">创建</button></div>`,
  )
  document.getElementById('a-create')!.onclick = createRelation
}

function showMergePanel() {
  mode = 'merge'
  const checkboxes = currentData.nodes
    .map(
      (n) =>
        `<label class="check-item">
          <input type="checkbox" class="m-src" value="${escapeHtml(n.id)}" />
          <span>${escapeHtml(n.id)}</span>
        </label>`,
    )
    .join('')
  showPanel(
    '合并实体（源并入目标）',
    `
      <label>选择要合并的源实体（可多选，合并后删除）</label>
      <div class="check-list" id="m-sources">${checkboxes}</div>
      <label>目标实体</label>
      <select id="f-target">${entityOptions()}</select>
    `,
    `<div class="row"><button class="primary" id="a-merge">合并</button></div>`,
  )
  document.getElementById('a-merge')!.onclick = doMerge
}

// ---- 操作 ----

async function saveEntity() {
  const type = (document.getElementById('f-type') as HTMLInputElement).value
  const desc = (document.getElementById('f-desc') as HTMLTextAreaElement).value
  try {
    await api.editEntity(selectedNodeId, type, desc)
    setStatus('实体已保存')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`保存失败: ${(err as Error).message}`, true)
  }
}

async function deleteEntity() {
  if (!confirm(`确定删除实体「${selectedNodeId}」及其所有关系？`)) return
  try {
    await api.deleteEntity(selectedNodeId)
    setStatus('实体已删除')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`删除失败: ${(err as Error).message}`, true)
  }
}

async function saveRelation() {
  if (!selectedEdge) return
  const desc = (document.getElementById('f-desc') as HTMLTextAreaElement).value
  const keywords = (document.getElementById('f-keywords') as HTMLInputElement).value
  try {
    await api.editRelation(selectedEdge.source, selectedEdge.target, desc, keywords)
    setStatus('关系已保存')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`保存失败: ${(err as Error).message}`, true)
  }
}

async function deleteRelation() {
  if (!selectedEdge) return
  if (!confirm(`确定删除关系「${selectedEdge.source} → ${selectedEdge.target}」？`)) return
  try {
    await api.deleteRelation(selectedEdge.source, selectedEdge.target)
    setStatus('关系已删除')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`删除失败: ${(err as Error).message}`, true)
  }
}

async function createEntity() {
  const name = (document.getElementById('f-name') as HTMLInputElement).value.trim()
  const type = (document.getElementById('f-type') as HTMLInputElement).value.trim()
  const desc = (document.getElementById('f-desc') as HTMLTextAreaElement).value.trim()
  if (!name) return setStatus('实体名不能为空', true)
  try {
    await api.createEntity(name, type, desc)
    setStatus('实体已创建')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`创建失败: ${(err as Error).message}`, true)
  }
}

async function createRelation() {
  const source = (document.getElementById('f-source') as HTMLSelectElement).value
  const target = (document.getElementById('f-target') as HTMLSelectElement).value
  const desc = (document.getElementById('f-desc') as HTMLTextAreaElement).value.trim()
  const keywords = (document.getElementById('f-keywords') as HTMLInputElement).value.trim()
  if (source === target) return setStatus('源和目标不能相同', true)
  try {
    await api.createRelation(source, target, desc, keywords)
    setStatus('关系已创建')
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`创建失败: ${(err as Error).message}`, true)
  }
}

async function doMerge() {
  const sources = Array.from(
    document.querySelectorAll<HTMLInputElement>('.m-src:checked'),
  ).map((c) => c.value)
  const target = (document.getElementById('f-target') as HTMLSelectElement).value
  if (sources.length === 0) return setStatus('至少选择一个源实体', true)
  if (sources.includes(target)) return setStatus('目标实体不能同时是源', true)
  try {
    const r = await api.merge(sources, target)
    setStatus(`合并完成：转移到目标的关系 ${r.relationships_transferred} 条`)
    await loadGraph()
    hidePanel()
  } catch (err) {
    setStatus(`合并失败: ${(err as Error).message}`, true)
  }
}

// ---- 文档管理 ----

function showDocumentsPanel() {
  mode = 'documents'
  showPanel(
    '文档管理',
    `
      <label>文档标题</label>
      <input id="d-title" placeholder="同一标题重复上传 = 覆盖更新" />
      <label>上传文件（docx / xlsx / pptx / pdf / txt / md）</label>
      <div class="row file-row">
        <input type="file" id="d-file" accept=".txt,.md,.docx,.xlsx,.pptx,.pdf" />
        <button class="primary" id="a-upload-file">上传文件</button>
      </div>
      <label>或粘贴文本</label>
      <textarea id="d-content" placeholder="粘贴文档文本..."></textarea>
      <div class="doc-list" id="d-list"></div>
    `,
    `<div class="row"><button class="primary" id="a-upload">上传 / 更新</button></div>`,
  )
  document.getElementById('a-upload')!.onclick = uploadDocument
  document.getElementById('a-upload-file')!.onclick = uploadFileDocument
  renderDocList()
}

async function uploadFileDocument() {
  const input = document.getElementById('d-file') as HTMLInputElement
  const file = input.files && input.files[0]
  if (!file) return setStatus('请先选择文件', true)
  const title = (document.getElementById('d-title') as HTMLInputElement).value.trim()
  const btn = document.getElementById('a-upload-file') as HTMLButtonElement
  btn.disabled = true
  btn.textContent = '解析中…'
  setStatus(`正在解析「${file.name}」并构建图谱，可能需要 20–30 秒，请勿关闭…`)
  try {
    const r = await api.uploadFile(title || null, file)
    setStatus(
      `文档「${r.title}」${r.created ? '已上传' : '已更新'}：${r.entity_count} 实体 · ${r.relation_count} 关系（${file.name}）`,
    )
    input.value = ''
    await renderDocList()
    await loadGraph()
  } catch (err) {
    setStatus(`上传失败: ${(err as Error).message}`, true)
  } finally {
    btn.disabled = false
    btn.textContent = '上传文件'
  }
}

async function renderDocList() {
  const listEl = document.getElementById('d-list')
  if (!listEl) return
  try {
    const { documents } = await api.listDocuments()
    if (documents.length === 0) {
      listEl.innerHTML = '<div class="doc-empty">暂无文档</div>'
      return
    }
    listEl.innerHTML = documents
      .map(
        (d: DocumentInfo) => `
          <div class="doc-item">
            <div class="doc-meta">
              <span class="doc-title">${escapeHtml(d.title)}</span>
              <span class="doc-stats">${d.entity_count} 实体 · ${d.relation_count} 关系</span>
            </div>
            <button class="doc-del" data-id="${escapeHtml(d.doc_id)}">删除</button>
          </div>`,
      )
      .join('')
    listEl.querySelectorAll<HTMLButtonElement>('.doc-del').forEach((btn) => {
      btn.onclick = () => deleteDocument(btn.dataset.id!)
    })
  } catch (err) {
    listEl.innerHTML = `<div class="doc-empty">加载失败: ${escapeHtml((err as Error).message)}</div>`
  }
}

async function uploadDocument() {
  const title = (document.getElementById('d-title') as HTMLInputElement).value.trim()
  const content = (document.getElementById('d-content') as HTMLTextAreaElement).value.trim()
  if (!content) return setStatus('文档内容不能为空', true)
  const btn = document.getElementById('a-upload') as HTMLButtonElement
  btn.disabled = true
  btn.textContent = '解析中…'
  setStatus('正在解析文档并构建图谱，可能需要 20–30 秒，请勿关闭…')
  try {
    const r = await api.uploadDocument(title || 'untitled', content)
    setStatus(
      `文档「${r.doc_id}」${r.created ? '已上传' : '已更新'}：${r.entity_count} 实体 · ${r.relation_count} 关系`,
    )
    ;(document.getElementById('d-content') as HTMLTextAreaElement).value = ''
    await renderDocList()
    await loadGraph()
  } catch (err) {
    setStatus(`上传失败: ${(err as Error).message}`, true)
  } finally {
    btn.disabled = false
    btn.textContent = '上传 / 更新'
  }
}

async function deleteDocument(docId: string) {
  if (!confirm(`确定删除文档「${docId}」？其独有实体/关系将从图中清理。`)) return
  try {
    await api.deleteDocument(docId)
    setStatus(`文档「${docId}」已删除`)
    await renderDocList()
    await loadGraph()
  } catch (err) {
    setStatus(`删除失败: ${(err as Error).message}`, true)
  }
}

// ---- 检索（图上路径高亮：错点实环 / 证据虚环 / 捞到未用不上色） ----

async function doQuery() {
  const q = (document.getElementById('query-input') as HTMLInputElement).value.trim()
  if (!q) return setStatus('请输入检索问题', true)
  setStatus('检索中…')
  try {
    const r = await api.query(q)
    const layers = r.trace.hit_layers
    // 高亮集合：实体带层级；路径上的端点若未被实体列表覆盖，按 path 层补上
    const highlight = new Map<string, string>()
    r.trace.entities.forEach((e) => highlight.set(e.name, e.layer || 'cited'))
    const rels = new Map<string, string>()
    r.trace.relationships.forEach((rel) => {
      rels.set(`${rel.src}||${rel.tgt}`, rel.layer || 'path')
      if (!highlight.has(rel.src)) highlight.set(rel.src, 'path')
      if (!highlight.has(rel.tgt)) highlight.set(rel.tgt, 'path')
    })
    setStatus(`命中 ${highlight.size} 实体 · ${rels.size} 关系`)
    showAnswerPanel(q, r.answer, highlight.size, rels.size, layers, r.trace.retrieved)
    queryRounds.unshift({ entities: highlight, relationships: rels })
    if (queryRounds.length > 4) queryRounds.pop()
    renderQueryHighlight()
  } catch (err) {
    setStatus(`检索失败: ${(err as Error).message}`, true)
  }
}

function renderAnswerMarkdown(text: string): string {
  return escapeHtml(text)
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function showAnswerPanel(
  question: string,
  answer: string,
  entityCount: number,
  relationCount: number,
  layers?: HitLayers,
  retrieved?: RetrievedInfo,
) {
  document.getElementById('answer-title')!.textContent = `检索：${question}`
  const body: string[] = []

  const pathNodes = new Set<string>()
  ;(layers?.paths ?? []).forEach((p) =>
    p.paths.forEach((seq) => seq.slice(1, -1).forEach((n) => pathNodes.add(n))),
  )
  const anchorN = (layers?.anchors ?? []).length
  const citedN = (layers?.cited ?? []).length
  const head = retrieved
    ? `检索到 ${retrieved.entity_count} 实体 · ${retrieved.relation_count} 关系 → 答案落点 ${entityCount} 实体 · ${relationCount} 关系`
    : `命中 ${entityCount} 实体 · ${relationCount} 关系`
  body.push(
    `<div class="hit-badge">${head}（锚点 ${anchorN} · 答案引用 ${citedN} · 路径中间点 ${pathNodes.size}）</div>`,
  )

  const mode = layers?.anchor_mode
  const why: Record<string, string> = {
    vector_fallback: '问题里没有图上的实体名，锚点改按相似度兜底选取——这一步不可靠，已标注。',
    no_anchor: '问题和答案都没点到图上的实体名，不做分层，下面列的是检索上下文。',
    vdb_error: '向量库不可用，分数与锚点分层全部跳过（诚实降级，不编造）。',
  }
  if (mode && mode !== 'literal' && why[mode]) {
    body.push(`<div class="warn-badge">${why[mode]}</div>`)
  }

  const unmatched = layers?.unmatched_keywords ?? []
  if (unmatched.length) {
    const names = unmatched.map((k) => `「${escapeHtml(k)}」`).join('、')
    body.push(
      `<div class="warn-badge">问题里的 ${names} 图上没有对应实体——要么文档没写过，要么该合并的没合并；下方这些红圈不表示检索找到了依据。</div>`,
    )
  }

  const disc = layers?.disconnected ?? []
  if (disc.length) {
    const txt = disc
      .map((d) => `${escapeHtml(d.a)} ↔ ${escapeHtml(d.b == null ? '（另一端未命中）' : d.b)}`)
      .join(' · ')
    body.push(
      `<div class="warn-badge">图上无路径可连：${txt} —— 对比题本来就该分属两处，也可能是实体该合并。</div>`,
    )
  }

  const paths = layers?.paths ?? []
  if (paths.length) {
    const rows = paths.map((p) => {
      const alt = p.paths.length > 1 ? `<span class="path-alt">等长 ${p.paths.length} 条</span>` : ''
      const seq = p.paths.map((s) => s.map(escapeHtml).join(' → ')).join('<br>')
      return `<div class="path-line">${escapeHtml(p.from)} ⇄ ${escapeHtml(p.to)} · ${p.hops} 跳${alt}<br>${seq}</div>`
    })
    body.push(`<div class="path-box"><div class="path-title">检索路径</div>${rows.join('')}</div>`)
  }

  const recall = layers?.recall_only ?? []
  if (recall.length) {
    const items = recall
      .map((rc) => `${escapeHtml(rc.name)}${rc.score == null ? '' : ` ${rc.score.toFixed(3)}`}`)
      .join(' · ')
    body.push(
      `<details class="recall"><summary>捞到未用 ${recall.length} 个</summary>` +
        `<div class="recall-note">向量召回到了，但既不是问题锚点、也不在答案路径上，所以图上不着色。分数只是旁证。</div>` +
        `<div>${items}</div></details>`,
    )
  }

  body.push(renderAnswerMarkdown(answer))
  document.getElementById('answer-body')!.innerHTML = body.join('')
  document.getElementById('answer-panel')!.classList.remove('hidden')
}

function makeDraggable(panelId: string, handleId: string) {
  const panelEl = document.getElementById(panelId)!
  const handleEl = document.getElementById(handleId)!
  let dragging = false
  let offsetX = 0
  let offsetY = 0

  handleEl.addEventListener('pointerdown', (e: PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return // 关闭按钮不触发拖拽
    dragging = true
    const rect = panelEl.getBoundingClientRect()
    offsetX = e.clientX - rect.left
    offsetY = e.clientY - rect.top
    try {
      handleEl.setPointerCapture(e.pointerId)
    } catch {
      /* 合成事件等场景下忽略 */
    }
  })
  handleEl.addEventListener('pointermove', (e: PointerEvent) => {
    if (!dragging) return
    const mainRect = document.getElementById('main')!.getBoundingClientRect()
    let left = e.clientX - mainRect.left - offsetX
    let top = e.clientY - mainRect.top - offsetY
    left = Math.max(0, Math.min(left, mainRect.width - panelEl.offsetWidth))
    top = Math.max(0, Math.min(top, mainRect.height - panelEl.offsetHeight))
    panelEl.style.left = `${left}px`
    panelEl.style.top = `${top}px`
    panelEl.style.bottom = 'auto'
  })
  const stop = () => {
    dragging = false
  }
  handleEl.addEventListener('pointerup', stop)
  handleEl.addEventListener('pointercancel', stop)
}

function renderQueryLegend() {
  const el = document.getElementById('query-legend')!
  if (queryRounds.length === 0) {
    el.classList.add('hidden')
    el.innerHTML = ''
    return
  }
  const rows = [
    `<div class="lg-row"><span class="lg-ring" style="border-color:${ROUND_COLORS[0]}"></span>本轮命中</div>`,
  ]
  if (queryRounds.length > 1) {
    const marks = queryRounds
      .slice(1)
      .map((_, i) => roundSup(i + 1))
      .join(' ')
    rows.push(`<div class="lg-row"><span class="lg-ring" style="border-color:${ROUND_COLORS[1]}"></span>更早轮次（角标 ${marks}）</div>`)
  }
  rows.push('<div class="lg-row"><span class="lg-ring lg-thick"></span>粗实环＝问题锚点</div>')
  rows.push('<div class="lg-row"><span class="lg-ring lg-dash"></span>虚线环＝答案引用 / 路径</div>')
  rows.push('<div class="lg-row lg-dim"><span class="lg-ring lg-plain"></span>灰色＝未命中（候选见左下角）</div>')
  el.innerHTML = rows.join('')
  el.classList.remove('hidden')
}

function renderQueryHighlight() {
  cy.elements().removeClass('dimmed').removeClass('hit')
  cy.nodes().forEach((n) => {
    n.data('hitAge', null)
    n.data('hitLayer', null)
    n.data('hitSup', null)
  })
  cy.edges().forEach((e) => {
    e.data('hitAge', null)
    e.data('hitLayer', null)
  })
  if (queryRounds.length === 0) {
    renderQueryLegend()
    return
  }

  const nodeAges = new Map<string, number>()
  const nodeLayers = new Map<string, string>()
  const edgeAges = new Map<string, number>()
  const edgeLayers = new Map<string, string>()
  queryRounds.forEach((round, i) => {
    round.entities.forEach((layer, name) => {
      if (!nodeAges.has(name)) {
        nodeAges.set(name, i)
        nodeLayers.set(name, layer)
      }
    })
    round.relationships.forEach((layer, key) => {
      if (!edgeAges.has(key)) {
        edgeAges.set(key, i)
        edgeLayers.set(key, layer)
      }
    })
  })

  cy.nodes().forEach((n) => {
    const age = nodeAges.get(String(n.id()))
    if (age !== undefined) {
      n.addClass('hit')
      n.data('hitAge', age)
      n.data('hitLayer', nodeLayers.get(String(n.id())) || 'cited')
      n.data('hitSup', roundSup(age))
    } else {
      n.addClass('dimmed')
    }
  })
  cy.edges().forEach((e) => {
    const key = `${e.source().id()}||${e.target().id()}`
    const rev = `${e.target().id()}||${e.source().id()}`
    const age = edgeAges.get(key) ?? edgeAges.get(rev)
    if (age !== undefined) {
      e.addClass('hit')
      e.data('hitAge', age)
      e.data('hitLayer', edgeLayers.get(key) ?? edgeLayers.get(rev) ?? 'path')
    } else {
      e.addClass('dimmed')
    }
  })
  renderQueryLegend()
}

// ---- 事件绑定 ----

cy.on('tap', 'node', (evt) => {
  highlightNeighbors(evt.target)
  showNodePanel(String(evt.target.id()))
})

cy.on('tap', 'edge', (evt) => {
  const e = evt.target
  highlightNeighbors(e)
  showEdgePanel(String(e.source().id()), String(e.target().id()))
})

cy.on('mouseover', 'edge', (evt) => {
  evt.target.addClass('edge-hover')
})

cy.on('mouseout', 'edge', (evt) => {
  evt.target.removeClass('edge-hover')
})

cy.on('tap', (evt) => {
  if (evt.target === cy) {
    cy.elements().removeClass('dimmed')
    hidePanel()
  }
})

document.getElementById('btn-refresh')!.onclick = loadGraph
document.getElementById('btn-add-entity')!.onclick = showNewEntityPanel
document.getElementById('btn-add-relation')!.onclick = showNewRelationPanel
document.getElementById('btn-merge')!.onclick = showMergePanel
document.getElementById('btn-docs')!.onclick = showDocumentsPanel
document.getElementById('btn-query')!.onclick = doQuery
document.getElementById('query-input')!.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') doQuery()
})
document.getElementById('btn-close-panel')!.onclick = hidePanel
document.getElementById('btn-close-answer')!.onclick = () => {
  document.getElementById('answer-panel')!.classList.add('hidden')
}
makeDraggable('answer-panel', 'answer-head')

window.addEventListener('resize', () => {
  cy.resize()
})

;(window as any).__gkb_showNodePanel__ = showNodePanel
;(window as any).__gkb_showEdgePanel__ = showEdgePanel
;(window as any).__gkb_data__ = () => currentData

loadGraph()
