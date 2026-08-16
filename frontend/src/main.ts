import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'
import './style.css'
import { api, GraphData } from './api'

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
}

// ---- 详情面板 ----

const panel = document.getElementById('panel')!
const panelTitle = document.getElementById('panel-title')!
const panelForm = document.getElementById('panel-form')!
const panelActions = document.getElementById('panel-actions')!

type Mode = 'node' | 'edge' | 'new-entity' | 'new-relation' | 'merge'
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
document.getElementById('btn-close-panel')!.onclick = hidePanel

window.addEventListener('resize', () => {
  cy.resize()
})

;(window as any).__gkb_showNodePanel__ = showNodePanel
;(window as any).__gkb_showEdgePanel__ = showEdgePanel
;(window as any).__gkb_data__ = () => currentData

loadGraph()
