/**
 * Visual workflow builder — an infinite pan/zoom canvas.
 *
 * Nodes are HTML cards positioned in world coordinates; edges are SVG paths
 * drawn in a world-space layer beneath them. Drag from a node's output port
 * to another node's input port to connect. One click selects; the inspector
 * edits config and the on/off switch; Delete removes.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type Workflow,
  type WorkflowDefinition,
  type WorkflowNode,
  type WorkflowNodeSpec,
  type WorkflowRun,
} from '../api'

interface CanvasNode extends WorkflowNode {
  position: { x: number; y: number }
}

const NODE_W = 208

/** Palette → accent per category. */
const CATEGORY_STYLE: Record<string, { ring: string; chip: string }> = {
  'Video processing': { ring: 'border-sodium-600/60', chip: 'bg-sodium-600/20 text-sodium-300' },
  Utilities: { ring: 'border-sky-600/60', chip: 'bg-sky-600/20 text-sky-300' },
}

function styleFor(category: string) {
  return CATEGORY_STYLE[category] ?? { ring: 'border-ink-600', chip: 'bg-ink-700 text-ink-300' }
}

export function Workflows() {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [specs, setSpecs] = useState<WorkflowNodeSpec[]>([])
  const [current, setCurrent] = useState<Workflow | null>(null)
  const [nodes, setNodes] = useState<CanvasNode[]>([])
  const [edges, setEdges] = useState<{ from: string; to: string }[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [name, setName] = useState('New workflow')

  // Canvas transform
  const [pan, setPan] = useState({ x: 60, y: 40 })
  const [zoom, setZoom] = useState(1)

  // Interaction state
  const dragNode = useRef<{ id: string; dx: number; dy: number } | null>(null)
  const panning = useRef<{ x: number; y: number } | null>(null)
  const linking = useRef<{ from: string; x: number; y: number } | null>(null)
  const [linkPreview, setLinkPreview] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null)

  const selected = nodes.find((n) => n.id === selectedId) ?? null
  const specOf = useCallback(
    (type: string) => specs.find((s) => s.type === type) ?? null,
    [specs],
  )

  const refreshList = useCallback(() => {
    api.listWorkflows().then(setWorkflows).catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    refreshList()
    api.workflowNodes().then(setSpecs).catch(() => undefined)
  }, [refreshList])

  const openWorkflow = useCallback((wf: Workflow) => {
    setCurrent(wf)
    setName(wf.name)
    const def = wf.definition
    setNodes(
      (def.nodes ?? []).map((n, i) => ({
        ...n,
        position: n.position ?? { x: 60 + (i % 4) * 260, y: 60 + Math.floor(i / 4) * 140 },
      })),
    )
    setEdges(def.edges ?? [])
    setSelectedId(null)
    setError('')
    api.workflowRuns(wf.id, 10).then(setRuns).catch(() => undefined)
  }, [])

  const newWorkflow = () => {
    setCurrent(null)
    setName('New workflow')
    setNodes([])
    setEdges([])
    setSelectedId(null)
    setRuns([])
  }

  const addNode = (spec: WorkflowNodeSpec) => {
    const id = `n${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`
    const world = screenToWorld({ x: 420, y: 260 }, pan, zoom)
    setNodes((ns) => [
      ...ns,
      { id, type: spec.type, enabled: true, config: {}, position: { x: world.x, y: world.y } },
    ])
    setSelectedId(id)
  }

  const definition = (): WorkflowDefinition => ({
    nodes: nodes.map(({ id, type, enabled, config, position }) => ({
      id, type, enabled, config, position,
    })),
    edges,
  })

  const save = async () => {
    setError('')
    try {
      if (current) {
        const saved = await api.saveWorkflow(current.id, definition(), name)
        setCurrent(saved)
        setStatus(`Saved as version ${saved.version}.`)
      } else {
        const created = await api.createWorkflow(name, definition())
        setCurrent(created)
        setStatus('Workflow created.')
      }
      refreshList()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const run = async () => {
    if (!current) {
      setError('Save the workflow first.')
      return
    }
    setError('')
    setStatus('Running…')
    try {
      const result = await api.runWorkflow(current.id)
      setStatus(`Run ${result.status}: ${result.nodes.filter((n) => n.status === 'succeeded').length}/${result.nodes.length} nodes OK.`)
      api.workflowRuns(current.id, 10).then(setRuns).catch(() => undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  const removeNode = (id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id))
    setEdges((es) => es.filter((e) => e.from !== id && e.to !== id))
    setSelectedId(null)
  }

  const toggleNode = (id: string) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, enabled: n.enabled === false } : n)))
  }

  const updateConfig = (id: string, key: string, value: string) => {
    setNodes((ns) =>
      ns.map((n) => (n.id === id ? { ...n, config: { ...n.config, [key]: value } } : n)),
    )
  }

  // -- pointer handling -------------------------------------------------------

  const toCanvas = (e: React.PointerEvent): { x: number; y: number } => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  function screenToWorld(p: { x: number; y: number }, pan: { x: number; y: number }, zoom: number) {
    return { x: (p.x - pan.x) / zoom, y: (p.y - pan.y) / zoom }
  }

  const onPointerDown = (e: React.PointerEvent) => {
    const p = toCanvas(e)
    if (e.button === 1 || e.button === 2 || (!e.shiftKey && e.button === 0 && (e.target as HTMLElement).dataset.canvas === 'bg')) {
      panning.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
      setSelectedId(null)
    }
    if (e.button === 0) {
      // Start a link from an output port.
      const port = (e.target as HTMLElement).dataset
      if (port.portFrom) {
        const from = nodes.find((n) => n.id === port.portFrom)
        if (from) {
          linking.current = { from: from.id, x: p.x, y: p.y }
          setLinkPreview({
            x1: from.position.x + NODE_W, y1: from.position.y + 28,
            x2: p.x, y2: p.y,
          })
        }
      }
    }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const p = toCanvas(e)
    if (panning.current) {
      setPan({ x: e.clientX - panning.current.x, y: e.clientY - panning.current.y })
    } else if (linking.current) {
      setLinkPreview((prev) => (prev ? { ...prev, x2: p.x, y2: p.y } : prev))
    } else if (dragNode.current) {
      const { id, dx, dy } = dragNode.current
      const world = screenToWorld(p, pan, zoom)
      setNodes((ns) =>
        ns.map((n) =>
          n.id === id ? { ...n, position: { x: world.x - dx, y: world.y - dy } } : n,
        ),
      )
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    if (linking.current) {
      const target = (e.target as HTMLElement).dataset.portTo
      if (target && target !== linking.current.from) {
        setEdges((es) =>
          es.some((x) => x.from === linking.current!.from && x.to === target) ? es : [...es, { from: linking.current!.from, to: target }],
        )
      }
      linking.current = null
      setLinkPreview(null)
    }
    panning.current = null
    dragNode.current = null
  }

  // -- render -------------------------------------------------------------------

  const toScreen = (wx: number, wy: number) => ({ x: wx * zoom + pan.x, y: wy * zoom + pan.y })

  const nodeCenter = (id: string) => {
    const n = nodes.find((x) => x.id === id)
    if (!n) return { x: 0, y: 0 }
    const s = toScreen(n.position.x, n.position.y)
    return { x: s.x + (NODE_W * zoom) / 2, y: s.y + (28 * zoom) }
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] gap-4">
      {/* Left: workflow list + palette */}
      <aside className="w-64 shrink-0 space-y-4 overflow-y-auto">
        <section>
          <h2 className="mb-2 font-display text-lg text-ink-100">Workflows</h2>
          <button
            onClick={newWorkflow}
            className="mb-2 w-full rounded border border-ink-700 px-2 py-1.5 text-left text-sm text-ink-200 hover:border-sodium-600 hover:text-sodium-300"
          >
            + New workflow
          </button>
          <ul className="space-y-1">
            {workflows.map((wf) => (
              <li key={`${wf.id}`}>
                <button
                  onClick={() => openWorkflow(wf)}
                  className={`w-full rounded border px-2 py-1.5 text-left text-sm ${
                    current?.id === wf.id
                      ? 'border-sodium-600 bg-sodium-600/10 text-sodium-200'
                      : 'border-ink-800 text-ink-300 hover:border-ink-600'
                  }`}
                >
                  <span className="block truncate">{wf.name}</span>
                  <span className="block text-xs text-ink-500">v{wf.version}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2 className="mb-2 font-display text-lg text-ink-100">Nodes</h2>
          <ul className="space-y-1">
            {specs.map((spec) => (
              <li key={spec.type}>
                <button
                  draggable
                  onClick={() => addNode(spec)}
                  title={`${spec.description}\nClick to add`}
                  className="w-full cursor-grab rounded border border-ink-800 px-2 py-1.5 text-left text-sm text-ink-300 hover:border-sodium-600 hover:text-sodium-300"
                >
                  <span className={`mr-1.5 inline-block rounded px-1 text-[10px] uppercase ${styleFor(spec.category).chip}`}>
                    {spec.category.split(' ')[0]}
                  </span>
                  {spec.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>

      {/* Canvas */}
      <div className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-ink-800 bg-ink-950">
        <div
          data-canvas="bg"
          className="absolute inset-0 cursor-grab active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onContextMenu={(e) => e.preventDefault()}
        >
          <svg className="pointer-events-none absolute inset-0 h-full w-full">
            {edges.map((e) => {
              const a = nodeCenter(e.from)
              const b = nodeCenter(e.to)
              const midX = (a.x + b.x) / 2
              return (
                <path
                  key={`${e.from}-${e.to}`}
                  d={`M ${a.x} ${a.y} C ${midX} ${a.y}, ${midX} ${b.y}, ${b.x} ${b.y}`}
                  stroke="rgb(90 130 90)"
                  strokeWidth={2}
                  fill="none"
                />
              )
            })}
            {linkPreview && (
              <path
                d={`M ${linkPreview.x1} ${linkPreview.y1} L ${linkPreview.x2} ${linkPreview.y2}`}
                stroke="rgb(160 160 160)"
                strokeDasharray="4 4"
                strokeWidth={2}
                fill="none"
              />
            )}
          </svg>

          {nodes.map((n) => {
            const spec = specOf(n.type)
            const s = toScreen(n.position.x, n.position.y)
            const st = styleFor(spec?.category ?? '')
            return (
              <div
                key={n.id}
                className={`absolute select-none rounded border bg-ink-900 shadow-lg ${st.ring} ${
                  selectedId === n.id ? 'ring-2 ring-sodium-500' : ''
                } ${n.enabled === false ? 'opacity-50' : ''}`}
                style={{ left: s.x, top: s.y, width: NODE_W * zoom, transform: `scale(${zoom})`, transformOrigin: 'top left' }}
                onPointerDown={(e) => {
                  const p = toCanvas(e.nativeEvent ? (e as unknown as React.PointerEvent) : e)
                  const world = screenToWorld(p, pan, zoom)
                  dragNode.current = { id: n.id, dx: world.x - n.position.x, dy: world.y - n.position.y }
                  setSelectedId(n.id)
                  e.stopPropagation()
                }}
              >
                <div className="flex items-center justify-between gap-1 border-b border-ink-800 px-2 py-1.5">
                  <span className="truncate text-sm text-ink-100">{spec?.name ?? n.type}</span>
                  <button
                    title={n.enabled === false ? 'Enable node' : 'Disable node'}
                    onClick={(e) => { e.stopPropagation(); toggleNode(n.id) }}
                    className={`h-3 w-6 rounded-full transition ${n.enabled === false ? 'bg-ink-600' : 'bg-sodium-500'}`}
                  >
                    <span
                      className={`block h-2.5 w-2.5 rounded-full bg-ink-950 transition ${
                        n.enabled === false ? 'translate-x-0' : 'translate-x-3'
                      }`}
                    />
                  </button>
                </div>
                <div
                  data-port-to={n.id}
                  title="Drop to connect"
                  className="mx-2 my-1 h-4 rounded bg-ink-800/60 text-center text-[10px] leading-4 text-ink-500"
                >
                  in
                </div>
                <div
                  data-port-from={n.id}
                  title="Drag to connect"
                  className="mx-2 mb-1.5 h-4 rounded bg-ink-800/60 text-center text-[10px] leading-4 text-ink-500"
                >
                  out
                </div>
              </div>
            )
          })}
        </div>

        {/* Zoom controls */}
        <div className="absolute bottom-3 right-3 flex gap-1">
          <button onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.1).toFixed(2)))} className="rounded border border-ink-700 bg-ink-900 px-2 py-0.5 text-ink-300">−</button>
          <span className="rounded border border-ink-800 bg-ink-900 px-2 py-0.5 text-xs text-ink-400">{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((z) => Math.min(1.6, +(z + 0.1).toFixed(2)))} className="rounded border border-ink-700 bg-ink-900 px-2 py-0.5 text-ink-300">+</button>
        </div>
      </div>

      {/* Inspector */}
      <aside className="w-72 shrink-0 space-y-4 overflow-y-auto">
        <section className="rounded border border-ink-800 p-3">
          <h2 className="mb-2 font-display text-lg text-ink-100">{current ? 'Edit workflow' : 'New workflow'}</h2>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mb-2 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm text-ink-100"
            placeholder="Workflow name"
          />
          <div className="flex gap-2">
            <button onClick={save} className="flex-1 rounded bg-sodium-600 px-2 py-1.5 text-sm font-medium text-ink-950 hover:bg-sodium-500">
              {current ? 'Save version' : 'Create'}
            </button>
            <button onClick={run} disabled={!current} className="flex-1 rounded border border-sodium-600 px-2 py-1.5 text-sm text-sodium-300 hover:bg-sodium-600/10 disabled:opacity-40">
              Run
            </button>
          </div>
          {status && <p className="mt-2 text-xs text-ink-400">{status}</p>}
          {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </section>

        {selected && (
          <section className="rounded border border-ink-800 p-3">
            <h3 className="mb-1 font-medium text-ink-100">{specOf(selected.type)?.name ?? selected.type}</h3>
            <p className="mb-2 text-xs text-ink-400">{specOf(selected.type)?.description}</p>
            {Object.entries(specOf(selected.type)?.config_schema ?? {}).map(([key]) => (
              <label key={key} className="mb-2 block text-xs text-ink-300">
                {key}
                <input
                  defaultValue={String(selected.config?.[key] ?? '')}
                  onBlur={(e) => updateConfig(selected.id, key, e.target.value)}
                  className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm text-ink-100"
                />
              </label>
            ))}
            <div className="flex gap-2">
              <button onClick={() => toggleNode(selected.id)} className="flex-1 rounded border border-ink-700 px-2 py-1 text-xs text-ink-300 hover:border-sodium-600">
                {selected.enabled === false ? 'Enable' : 'Disable'}
              </button>
              <button onClick={() => removeNode(selected.id)} className="flex-1 rounded border border-red-800 px-2 py-1 text-xs text-red-300 hover:bg-red-900/30">
                Delete node
              </button>
            </div>
          </section>
        )}

        <section className="rounded border border-ink-800 p-3">
          <h3 className="mb-2 font-medium text-ink-100">Recent runs</h3>
          {runs.length === 0 && <p className="text-xs text-ink-500">No runs yet.</p>}
          <ul className="space-y-1">
            {runs.map((r) => (
              <li key={r.id} className="flex items-center justify-between text-xs">
                <span className="text-ink-400">{new Date(r.started_at).toLocaleTimeString()}</span>
                <span
                  className={
                    r.status === 'succeeded' ? 'text-sodium-400' : r.status === 'failed' ? 'text-red-400' : 'text-ink-300'
                  }
                >
                  {r.status}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  )
}
