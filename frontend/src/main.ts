import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'
import './style.css'
import { api, GraphData, DocumentInfo } from './api'

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

// 检索多轮颜色：最新一轮（age=0）深红，历史逐轮明显变浅变细变淡
// 色阶拉开到「红 → 浅粉」量级，避免第 2 档看着仍像红色
const AGE_COLORS = ['#c81e2e', '#ef8a96', '#f7c3ca', '#fbe2e6']
const AGE_WIDTHS = [5, 2.5, 2, 1.5]
const AGE_OPACITY = [1, 0.72, 0.58, 0.46]
// 本轮命中节点略放大，缩小时也能一眼看出哪轮是最新的
const AGE_SIZE = [40, 34, 32, 32]

function ageIndex(age: number): number {
  return Math.min(Math.max(Math.floor(Number(age) || 0), 0), AGE_COLORS.length - 1)
}

function ageColor(age: number): string {
  return AGE_COLORS[ageIndex(age)]
}

function ageWidth(age: number): number {
  return AGE_WIDTHS[ageIndex(age)]
}

function ageOpacity(age: number): number {
  return AGE_OPACITY[ageIndex(age)]
}

function ageSize(age: number): number {
  return AGE_SIZE[ageIndex(age)]
}

const cy = cytoscape({
  container: document.getElementById('cy')!,
  style: [
    {
      selector: 'node',
      style: {
        label: 'data(id)',
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
      selector: 'node.hit',
      style: {
        'border-width': (ele: any) => ageWidth(ele.data('hitAge')),
        'border-color': (ele: any) => ageColor(ele.data('hitAge')),
        opacity: (ele: any) => ageOpacity(ele.data('hitAge')),
        width: (ele: any) => ageSize(ele.data('hitAge')),
        height: (ele: any) => ageSize(ele.data('hitAge')),
      },
    },
    {
      selector: 'edge.hit',
      style: {
        width: (ele: any) => ageWidth(ele.data('hitAge')),
        'line-color': (ele: any) => ageColor(ele.data('hitAge')),
        'target-arrow-color': (ele: any) => ageColor(ele.data('hitAge')),
        opacity: (ele: any) => ageOpacity(ele.data('hitAge')),
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
const queryRounds: { entities: Set<string>; relationships: Set<string> }[] = []

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
    data: { id: n.id, type: n.type, description: n.description },
  }))
  const edges = data.edges.map((e, i) => ({
    data: {
      id: `e${i}:${e.source}:${e.target}`,
      source: e.source,
      target: e.target,
      description: e.description,
      keywords: e.keywords,
    },
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
      <label>文档内容</label>
      <textarea id="d-content" placeholder="粘贴文档文本..."></textarea>
      <div class="doc-list" id="d-list"></div>
    `,
    `<div class="row"><button class="primary" id="a-upload">上传 / 更新</button></div>`,
  )
  document.getElementById('a-upload')!.onclick = uploadDocument
  renderDocList()
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

// ---- 检索（图上路径高亮 + 多轮颜色演进） ----

async function doQuery() {
  const q = (document.getElementById('query-input') as HTMLInputElement).value.trim()
  if (!q) return setStatus('请输入检索问题', true)
  setStatus('检索中…')
  try {
    const r = await api.query(q)
    const hitEntities = new Set(r.trace.entities.map((e) => e.name))
    const hitRelationships = new Set(r.trace.relationships.map((rel) => `${rel.src}||${rel.tgt}`))
    setStatus(`命中 ${hitEntities.size} 实体 · ${hitRelationships.size} 关系`)
    showAnswerPanel(q, r.answer, hitEntities.size, hitRelationships.size)
    // 高亮集合：实体命中 + 关系两端点，保证「路径」上的节点与边一起高亮
    const highlightEntities = new Set(hitEntities)
    r.trace.relationships.forEach((rel) => {
      highlightEntities.add(rel.src)
      highlightEntities.add(rel.tgt)
    })
    queryRounds.unshift({ entities: highlightEntities, relationships: hitRelationships })
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

function showAnswerPanel(question: string, answer: string, entityCount: number, relationCount: number) {
  document.getElementById('answer-title')!.textContent = `检索：${question}`
  document.getElementById('answer-body')!.innerHTML =
    `<div class="hit-badge">命中 ${entityCount} 实体 · ${relationCount} 关系</div>` +
    renderAnswerMarkdown(answer)
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
  const rows = [`<div class="lg-row"><span class="lg-swatch" style="background:${ageColor(0)}"></span>本轮命中</div>`]
  for (let age = 1; age < queryRounds.length && age < AGE_COLORS.length; age++) {
    const label = age === 1 ? '上一轮' : '更早'
    rows.push(`<div class="lg-row"><span class="lg-swatch" style="background:${ageColor(age)}"></span>${label}</div>`)
  }
  rows.push('<div class="lg-row lg-dim"><span class="lg-swatch" style="background:#c9d1d9"></span>未命中</div>')
  el.innerHTML = rows.join('')
  el.classList.remove('hidden')
}

function renderQueryHighlight() {
  cy.elements().removeClass('dimmed').removeClass('hit')
  cy.nodes().forEach((n) => {
    n.data('hitAge', null)
  })
  cy.edges().forEach((e) => {
    e.data('hitAge', null)
  })
  if (queryRounds.length === 0) {
    renderQueryLegend()
    return
  }

  const nodeAges = new Map<string, number>()
  const edgeAges = new Map<string, number>()
  queryRounds.forEach((round, i) => {
    round.entities.forEach((name) => {
      if (!nodeAges.has(name)) nodeAges.set(name, i)
    })
    round.relationships.forEach((key) => {
      if (!edgeAges.has(key)) edgeAges.set(key, i)
    })
  })

  cy.nodes().forEach((n) => {
    const age = nodeAges.get(String(n.id()))
    if (age !== undefined) {
      n.addClass('hit')
      n.data('hitAge', age)
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
