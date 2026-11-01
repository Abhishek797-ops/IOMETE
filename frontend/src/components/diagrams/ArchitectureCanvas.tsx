"use client";

import * as React from "react";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { LayoutGrid, List, X } from "lucide-react";

import { usePrefersReducedMotion } from "@/lib/hooks";
import type { ArchitectureGraph, GraphLegendEntry, GraphNode } from "@/lib/types";

/**
 * What the canvas needs from a graph.
 *
 * `legend` is optional here, because a stored `ArchitectureRecommendation` carries it
 * optionally while the reference graph always has it. Widening the prop this way lets
 * both be passed without a cast; the legend panel simply does not render without one.
 */
type RenderableGraph = Omit<ArchitectureGraph, "legend"> & {
  legend?: GraphLegendEntry[];
};
import { cn } from "@/lib/utils";

import {
  Badge,
  Card,
  Eyebrow,
  GraphLegend,
  IconButton,
  NODE_CLAIM_PRESENTATION,
  NodeClaimBadge,
  SourceList,
  Tabs,
} from "@/components/ui";

/*
 * Layout.
 *
 * A deliberate layered layout rather than a force-directed one. This is an architecture
 * diagram, and the reader needs to see that data flows left to right through a fixed set
 * of tiers — a graph that settles into a pleasing blob loses the one thing the picture is
 * for. Columns come from the knowledge base's own layer ordering.
 */
const COLUMN_WIDTH = 248;
const ROW_HEIGHT = 112;
const NODE_WIDTH = 204;

interface CompassNodeData extends Record<string, unknown> {
  node: GraphNode;
  onSelect: (id: string) => void;
  selected: boolean;
}

function layoutNodes(
  graph: RenderableGraph,
  onSelect: (id: string) => void,
  selectedId: string | null,
): Node<CompassNodeData>[] {
  const layerOrder = new Map(graph.layers.map((layer) => [layer.id, layer.order]));
  const byLayer = new Map<string, GraphNode[]>();

  for (const node of graph.nodes) {
    const list = byLayer.get(node.layer) ?? [];
    list.push(node);
    byLayer.set(node.layer, list);
  }

  const columns = [...byLayer.keys()].sort(
    (a, b) => (layerOrder.get(a) ?? 99) - (layerOrder.get(b) ?? 99),
  );

  const tallest = Math.max(...[...byLayer.values()].map((list) => list.length), 1);

  return columns.flatMap((layerId, columnIndex) => {
    const nodes = byLayer.get(layerId) ?? [];
    // Centre each column vertically, so a column of two does not sit at the top beside a
    // column of six.
    const offset = ((tallest - nodes.length) * ROW_HEIGHT) / 2;

    return nodes.map((node, rowIndex) => ({
      id: node.id,
      type: "compass",
      position: { x: columnIndex * COLUMN_WIDTH, y: offset + rowIndex * ROW_HEIGHT },
      data: { node, onSelect, selected: selectedId === node.id },
      draggable: true,
      // Handles are fixed left/right so edges read as flow rather than wandering.
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));
  });
}

function layoutEdges(graph: RenderableGraph, selectedId: string | null): Edge[] {
  return graph.edges.map((edge) => {
    const touchesSelection =
      selectedId !== null && (edge.source === selectedId || edge.target === selectedId);
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: touchesSelection ? edge.label : undefined,
      // The claim status drives the stroke via CSS, so a conceptual placement is dashed
      // and a documented one is solid. See the react-flow block in globals.css.
      className: `edge-${edge.claim_status}`,
      animated: false,
      style: {
        strokeWidth: touchesSelection ? 2 : 1.25,
        opacity: selectedId === null ? 0.85 : touchesSelection ? 1 : 0.25,
      },
    };
  });
}

/** A node. Styled by claim status so a proposal never looks like a documented fact. */
function CompassNode({ data }: NodeProps<Node<CompassNodeData>>) {
  const { node, onSelect, selected } = data;
  const presentation = NODE_CLAIM_PRESENTATION[node.claim_status];

  return (
    <button
      type="button"
      onClick={() => onSelect(node.id)}
      aria-pressed={selected}
      style={{ width: NODE_WIDTH }}
      className={cn(
        "group rounded-lg border-2 bg-surface-raised px-3 py-2.5 text-left shadow-subtle",
        "transition-[box-shadow,transform,border-color] duration-150",
        presentation.border,
        presentation.dashed && "border-dashed",
        selected
          ? "-translate-y-0.5 shadow-raised ring-2 ring-accent-500/40"
          : "hover:-translate-y-0.5 hover:shadow-raised",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0" />
      <span className="block truncate text-small font-medium text-ink">{node.label}</span>
      <span
        className={cn(
          "mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
          presentation.background,
          "text-ink-muted",
        )}
      >
        {presentation.label}
      </span>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0" />
    </button>
  );
}

const NODE_TYPES = { compass: CompassNode };

/**
 * The architecture playground.
 *
 * Two views of the same graph, switchable: an interactive canvas, and a plain grouped
 * list. The list is not a fallback — a drag-and-zoom canvas is effectively unusable with
 * a screen reader or on a phone, and the list is also the faster way to read every
 * component's purpose in order. Both are always available.
 */
export function ArchitectureCanvas({
  graph,
  className,
}: {
  graph: RenderableGraph;
  className?: string;
}) {
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const reduceMotion = usePrefersReducedMotion();

  const select = React.useCallback((id: string) => {
    setSelectedId((current) => (current === id ? null : id));
  }, []);

  const nodes = React.useMemo(
    () => layoutNodes(graph, select, selectedId),
    [graph, select, selectedId],
  );
  const edges = React.useMemo(() => layoutEdges(graph, selectedId), [graph, selectedId]);

  const selected = graph.nodes.find((node) => node.id === selectedId) ?? null;

  return (
    <div className={cn("space-y-4", className)}>
      <Tabs
        persistKey="architecture.view"
        items={[
          { id: "diagram", label: "Diagram", icon: <LayoutGrid /> },
          { id: "list", label: "Component list", icon: <List />, count: graph.nodes.length },
        ]}
      >
        {(view) =>
          view === "diagram" ? (
            <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
              <div
                className="h-[32rem] overflow-hidden rounded-lg border border-border bg-surface-sunken sm:h-[36rem]"
                role="application"
                aria-label={`${graph.title} — interactive diagram. A plain component list is available in the adjacent tab.`}
              >
                <ReactFlowProvider>
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={NODE_TYPES}
                    fitView
                    fitViewOptions={{ padding: 0.18 }}
                    minZoom={0.35}
                    maxZoom={1.6}
                    proOptions={{ hideAttribution: false }}
                    nodesConnectable={false}
                    edgesFocusable={false}
                    onPaneClick={() => setSelectedId(null)}
                    // Scroll-to-zoom hijacks the page scroll on a long page, which is
                    // the single most irritating thing an embedded canvas can do.
                    zoomOnScroll={false}
                    panOnScroll={false}
                    preventScrolling={false}
                    nodesDraggable
                  >
                    <Background
                      variant={BackgroundVariant.Dots}
                      gap={22}
                      size={1}
                      className="opacity-50"
                    />
                    <Controls showInteractive={false} position="bottom-left" />
                    {!reduceMotion && (
                      <MiniMap
                        pannable
                        zoomable
                        position="bottom-right"
                        className="!h-20 !w-32"
                      />
                    )}
                  </ReactFlow>
                </ReactFlowProvider>
              </div>

              <aside className="space-y-4">
                {selected ? (
                  <NodeDetail node={selected} onClose={() => setSelectedId(null)} />
                ) : (
                  <Card tone="sunken">
                    <Eyebrow as="h3">Pick a component</Eyebrow>
                    <p className="mt-2 text-small text-ink-muted">
                      Click any box to see what it does, why it is needed, what you get
                      from it, and the documentation page it was read from. Drag to
                      rearrange; use the controls to zoom.
                    </p>
                  </Card>
                )}
                {graph.legend && graph.legend.length > 0 && (
                  <Card tone="flat">
                    <GraphLegend legend={graph.legend} />
                  </Card>
                )}
              </aside>
            </div>
          ) : (
            <ComponentList graph={graph} />
          )
        }
      </Tabs>
    </div>
  );
}

function NodeDetail({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  return (
    <Card tone="raised" className="border-accent-200">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-h3 text-ink">{node.label}</h3>
          <div className="mt-1.5">
            <NodeClaimBadge status={node.claim_status} />
          </div>
        </div>
        <IconButton label="Close details" size="sm" onClick={onClose} className="shrink-0">
          <X />
        </IconButton>
      </div>

      <dl className="mt-4 space-y-3.5">
        <div>
          <dt className="text-micro uppercase text-ink-subtle">What it does</dt>
          <dd className="mt-1 text-small text-ink-muted">{node.description}</dd>
        </div>
        {node.detail.why_needed && (
          <div>
            <dt className="text-micro uppercase text-ink-subtle">Why it is needed</dt>
            <dd className="mt-1 text-small text-ink-muted">{node.detail.why_needed}</dd>
          </div>
        )}
        {node.detail.customer_gain && (
          <div>
            <dt className="text-micro uppercase text-accent-700 dark:text-accent-400">
              What you get
            </dt>
            <dd className="mt-1 text-small text-ink-muted">{node.detail.customer_gain}</dd>
          </div>
        )}
        {node.detail.uri_scheme && (
          <div>
            <dt className="text-micro uppercase text-ink-subtle">URI scheme</dt>
            <dd className="mt-1 font-mono text-small text-ink">{node.detail.uri_scheme}</dd>
          </div>
        )}
        {node.detail.note && (
          <div>
            <dt className="text-micro uppercase text-caution">Note</dt>
            <dd className="mt-1 text-small text-ink-muted">{node.detail.note}</dd>
          </div>
        )}
      </dl>

      {node.sources.length > 0 && (
        <div className="mt-4 border-t border-border pt-3.5">
          <Eyebrow as="h4">Read from</Eyebrow>
          <SourceList sources={node.sources} className="mt-2" />
        </div>
      )}
    </Card>
  );
}

/**
 * The plain list view.
 *
 * Grouped by layer in flow order, so reading top to bottom walks the same path the
 * diagram shows left to right.
 */
function ComponentList({ graph }: { graph: RenderableGraph }) {
  const layers = [...graph.layers].sort((a, b) => a.order - b.order);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        {layers.map((layer) => {
          const nodes = graph.nodes.filter((node) => node.layer === layer.id);
          if (nodes.length === 0) return null;
          return (
            <section key={layer.id}>
              <div className="flex flex-wrap items-baseline gap-2.5">
                <h3 className="text-h3 text-ink">{layer.label}</h3>
                <Badge tone="neutral" size="sm">
                  Step {layer.order}
                </Badge>
              </div>
              <p className="mt-1 text-small text-ink-muted">{layer.description}</p>

              <ul className="mt-3 space-y-2.5">
                {nodes.map((node) => {
                  const presentation = NODE_CLAIM_PRESENTATION[node.claim_status];
                  return (
                    <li key={node.id}>
                      <Card
                        tone="flat"
                        className={cn("border-l-2", presentation.border)}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2.5">
                          <h4 className="text-small font-medium text-ink">{node.label}</h4>
                          <NodeClaimBadge status={node.claim_status} />
                        </div>
                        <p className="mt-2 text-small text-ink-muted">{node.description}</p>
                        {node.detail.customer_gain && (
                          <p className="mt-2 text-small text-ink-muted">
                            <span className="font-medium text-ink">What you get: </span>
                            {node.detail.customer_gain}
                          </p>
                        )}
                        {node.sources.length > 0 && (
                          <div className="mt-2.5">
                            <SourceList sources={node.sources} inline label="source" />
                          </div>
                        )}
                      </Card>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>

      {graph.legend && graph.legend.length > 0 && (
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <Card tone="flat">
            <GraphLegend legend={graph.legend} />
          </Card>
        </aside>
      )}
    </div>
  );
}
