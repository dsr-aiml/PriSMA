"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow, getSmoothStepPath, type Edge, type EdgeProps, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import { SelectField } from "@/components/ui";
import type { Layout } from "@/lib/graph-layout";
import { ClaimDetails } from "@/components/claim-details";
import { Dialog, DialogTitle } from "@/components/dialog";
import { Icon, type IconName } from "@/components/icons";
import { Evidence, Report } from "@/lib/api";
import { classificationLabel } from "@/lib/presentation";

const WIDTH = 238, HEIGHT = 140;
const viewports=new Map<string,{x:number;y:number;zoom:number}>();
type ComponentData = { label: string; description: string; kind: string; classification: string; confidence: number; dim: boolean; focused: boolean;compact:boolean;sources:number;connections:number };
type ComponentNode = Node<ComponentData, "component">;
type LaneNode = Node<{ label: string }, "lane">;
type ConnectionData = { classification: string; active: boolean; dim: boolean; labelVisible: boolean; points?:{x:number;y:number}[];routeY?: number; sideRoute?: boolean; offset: number; inspect: () => void };
type ConnectionEdge = Edge<ConnectionData, "connection"> & { claim_id: string };

function kindIcon(kind: string): IconName {
  return ({ "source modules": "code", module_group: "code", resource: "link", application: "layers", schema: "database", frontend: "code", api: "server", auth: "shield", infrastructure: "cloud", gateway: "layers", database: "database", worker: "server", queue: "queue", search: "search", storage: "cloud", notification: "mail", monitoring: "activity", realtime: "activity", audit: "document", deployment: "layers", configuration: "layers", integration: "link", service: "link" } as Record<string, IconName>)[kind.split(" · ")[0]] ?? "server";
}

function ArchitectureNode({ data }: NodeProps<ComponentNode>) {
  return <div className={`architecture-node ${data.dim ? "is-muted" : ""} ${data.focused ? "is-focused" : ""} ${data.compact?"is-compact":""}`}>
    <Handle type="target" position={Position.Left} id="left-in" isConnectable={false} />
    <Handle type="source" position={Position.Left} id="left-out" isConnectable={false} />
    <Handle type="target" position={Position.Right} id="right-in" isConnectable={false} />
    <Handle type="source" position={Position.Right} id="right-out" isConnectable={false} />
    {data.compact ? <div className="node-compact-label"><strong title={data.label}>{data.label}</strong></div> : <div className="node-full-content">
      <div className="node-kind"><Icon name={kindIcon(data.kind)} /><span>{data.kind.replaceAll("_", " ")}</span></div>
      <strong title={data.label}>{data.label}</strong><p title={data.description}>{data.connections} connections · {data.sources} source records</p>
      <div className="node-assessment"><span>{classificationLabel(data.classification)}</span></div>
    </div>}
  </div>;
}

function LaneHeading({ data }: NodeProps<LaneNode>) {
  return <div className="lane-heading">{data.label}</div>;
}

function roundedPath(points: { x: number; y: number }[]) {
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length - 1; index++) {
    const previous = points[index - 1], point = points[index], next = points[index + 1];
    const before = Math.hypot(point.x - previous.x, point.y - previous.y), after = Math.hypot(next.x - point.x, next.y - point.y);
    if (!before || !after) continue;
    const radius = Math.min(12, before / 2, after / 2);
    const enter = { x: point.x - (point.x - previous.x) / before * radius, y: point.y - (point.y - previous.y) / before * radius };
    const exit = { x: point.x + (next.x - point.x) / after * radius, y: point.y + (next.y - point.y) / after * radius };
    path += ` L ${enter.x} ${enter.y} Q ${point.x} ${point.y} ${exit.x} ${exit.y}`;
  }
  const end = points.at(-1)!;
  return path + ` L ${end.x} ${end.y}`;
}

function ArchitectureConnection(props: EdgeProps<ConnectionEdge>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, label, data } = props;
  if (!data) return null;
  let [path, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 12, offset: 28 });
  if (data.points?.length) {
    path=roundedPath(data.points);const segments=data.points.slice(1).map((point,index)=>({a:data.points![index],b:point,length:Math.hypot(point.x-data.points![index].x,point.y-data.points![index].y),inner:index>0&&index<data.points!.length-2}));const segment=segments.sort((a,b)=>(b.inner?1:0)-(a.inner?1:0)||b.length-a.length)[0];labelX=(segment.a.x+segment.b.x)/2;labelY=(segment.a.y+segment.b.y)/2;
  } else if (data.sideRoute) {
    const x = Math.max(sourceX, targetX) + 34 + data.offset;
    path = roundedPath([{ x: sourceX, y: sourceY }, { x, y: sourceY }, { x, y: targetY }, { x: targetX, y: targetY }]);
    labelX = x; labelY = (sourceY + targetY) / 2;
  } else if (data.routeY !== undefined) {
    const exitX = sourceX + (sourcePosition === Position.Right ? 1 : -1) * (32 + data.offset);
    const enterX = targetX + (targetPosition === Position.Left ? -1 : 1) * (32 + data.offset);
    path = roundedPath([{ x: sourceX, y: sourceY }, { x: exitX, y: sourceY }, { x: exitX, y: data.routeY }, { x: enterX, y: data.routeY }, { x: enterX, y: targetY }, { x: targetX, y: targetY }]);
    labelX = (exitX + enterX) / 2; labelY = data.routeY;
  }
  const className = `architecture-connection ${data.classification} ${data.active ? "is-active" : ""} ${data.dim ? "is-muted" : ""}`;
  return <g className={className}>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={24} />
    {data.labelVisible && <EdgeLabelRenderer><button className="connection-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }} onClick={data.inspect}>{label}</button></EdgeLabelRenderer>}
  </g>;
}

const nodeTypes = { component: memo(ArchitectureNode), lane: memo(LaneHeading) };
const edgeTypes = { connection: memo(ArchitectureConnection) };
const reduceMotion = () => typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function Canvas({ report, dark, focused, hovered, setHovered, inspect, query = "", lane = "all" }: {
  report: Report; dark: boolean; focused: string; hovered: string; setHovered: (id: string) => void; inspect: (claim: string, component: string) => void; query?: string; lane?: string;
}) {
  const [instance, setInstance] = useState<ReactFlowInstance<Node, ConnectionEdge> | null>(null);
  const [zoom, setZoom] = useState(100);
  const [compact,setCompact] = useState(false);
  const updateZoom=useCallback((value:number)=>{setZoom(Math.round(value*100));setCompact(previous=>previous?value<.60:value<.48);},[]);
  const [layout,setLayout]=useState<Layout|null>(null);
  const viewportKey=report.nodes.map(node=>node.id).join("|")+"|"+lane+"|"+query;
  const touched=useRef(viewports.has(viewportKey)),fitted=useRef(false);
  useEffect(()=>{touched.current=viewports.has(viewportKey);fitted.current=false;const saved=viewports.get(viewportKey);if(saved&&instance)void instance.setViewport(saved);},[viewportKey,instance]);
  useEffect(()=>{let active=true;setLayout(null);void import("@/lib/graph-layout").then(module=>module.layoutGraph(report,WIDTH,HEIGHT)).then(result=>{if(active){setLayout(result);}}).catch(()=>{/* Existing positions remain available. */});return()=>{active=false;};},[report]);
  useEffect(()=>{if(layout&&instance&&!touched.current&&!fitted.current){fitted.current=true;void instance.fitView({padding:.12,duration:reduceMotion()?0:280,maxZoom:1});}},[layout,instance]);

  const visible = useMemo(() => report.nodes.filter(node => (lane === "all" || node.lane === lane) && `${node.label} ${node.kind} ${node.context ?? ""} ${node.description ?? ""}`.toLowerCase().includes(query.toLowerCase())), [report.nodes, query, lane]);
  const visibleIds = useMemo(() => new Set(visible.map(node => node.id)), [visible]);
  const connected = useMemo(() => {
    const ids = new Set([focused]);
    report.edges.forEach(edge => { if (edge.source === focused || edge.target === focused) { ids.add(edge.source); ids.add(edge.target); } });
    return ids;
  }, [report.edges, focused]);
  const nodes: Node[] = useMemo(() => {
    const components = visible.map(node => ({ id: node.id, type: "component", position: layout?.positions[node.id]??node.position,
      data: { label: node.label, kind: node.kind==="module_group" ? "source modules" : node.context ? node.kind + " · " + node.context : node.kind, description: node.description ?? "Select to inspect source evidence", classification: node.classification, confidence: node.confidence, sources:new Set(report.claims.filter(c=>(node.claim_ids??[node.claim_id]).includes(c.id)).flatMap(c=>c.supporting_evidence_ids)).size,connections:report.edges.filter(edge=>edge.source===node.id||edge.target===node.id).length, compact,focused: focused === node.id, dim: !!focused && visibleIds.has(focused) && !connected.has(node.id) },
      style: { width: WIDTH, height: HEIGHT }, ariaLabel: `${node.label}. ${classificationLabel(node.classification)}. Select for evidence.`,
    }));
    const columns = new Map<number, string>();
    visible.forEach(node => { if (node.lane) !([...columns.values()].includes(node.lane)) && columns.set(node.position.x, node.lane); });
    const headings = (layout?[]:[...columns]).map(([x, label]) => ({ id: `lane-${x}`, type: "lane", position: { x, y: Math.min(...visible.filter(node => node.position.x === x).map(node => node.position.y)) - 54 }, data: { label }, selectable: false, focusable: false, style: { width: WIDTH } }));
    return [...headings, ...components];
  }, [visible, focused, connected, visibleIds,layout,compact,report.claims,report.edges]);
  const edges: ConnectionEdge[] = useMemo(() => report.edges.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target)).map((edge, index) => {
    const sourceOriginal=report.nodes.find(node=>node.id===edge.source)!,targetOriginal=report.nodes.find(node=>node.id===edge.target)!;
    const source={...sourceOriginal,position:layout?.positions[edge.source]??sourceOriginal.position},target={...targetOriginal,position:layout?.positions[edge.target]??targetOriginal.position};
    const sameColumn = source.position.x === target.position.x;
    const forwards = target.position.x > source.position.x;
    const active = edge.source === focused || edge.target === focused || edge.id === hovered;
    return { ...edge, type: "connection", sourceHandle: layout || sameColumn || forwards ? "right-out" : "left-out", targetHandle: !layout && (sameColumn || !forwards) ? "right-in" : "left-in",
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: active ? "var(--graph-active)" : "var(--graph-line)" },
      data: { points:layout?.routes[edge.id],classification: edge.classification, active, dim: !!focused && visibleIds.has(focused) && !active, labelVisible: active,
        sideRoute: sameColumn, routeY: !sameColumn && Math.abs(source.position.x - target.position.x) > 400 ? source.position.y + HEIGHT + 20 + (index % 3) * 8 : undefined,
        offset: (index % 3) * 6, inspect: () => inspect(edge.claim_id, edge.source),
      }, ariaLabel: `${source.label} to ${target.label}. ${edge.label}. ${classificationLabel(edge.classification)} connection.`, focusable: true,
    };
  }), [report, visibleIds, focused, hovered, inspect,layout]);
  const fit = useCallback(() => { instance?.fitView({ padding: 0.1, duration: reduceMotion() ? 0 : 280, maxZoom: 1 }); }, [instance]);
  return <div className="graph-canvas" role="region" aria-label="Architecture graph">
    {visible.length === 0 && <div className="graph-no-results">{report.nodes.length ? "No components match this view." : <div><strong>No components</strong><p>{report.run?.provider === "rules" ? "The selected sources contain no supported structural boundaries. Add technical sources or interpret the collected prose with Local inference." : "The collected sources did not establish components with accepted supporting evidence."}</p></div>}</div>}
    <ReactFlow<Node, ConnectionEdge> proOptions={{hideAttribution:true}} nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
      onInit={flow => { setInstance(flow); updateZoom(flow.getZoom()); }} onMoveStart={event=>{if(event)touched.current=true;}} onMove={(_,viewport)=>{updateZoom(viewport.zoom);viewports.set(viewportKey,viewport);if(viewports.size>20)viewports.delete(viewports.keys().next().value!);}} defaultViewport={viewports.get(viewportKey)}
      onNodeClick={(_, node) => { const component = report.nodes.find(item => item.id === node.id); if (component) inspect(component.claim_id, component.id); }}
      onEdgeClick={(_, edge) => inspect(edge.claim_id, edge.source)} onEdgeMouseEnter={(_, edge) => setHovered(edge.id)} onEdgeMouseLeave={() => setHovered("")}
      onlyRenderVisibleElements fitView={!viewports.has(viewportKey)} fitViewOptions={{ padding: 0.12, maxZoom: 1 }} minZoom={0.08} maxZoom={2} nodesDraggable={false} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null}
      colorMode={dark ? "dark" : "light"} panOnScroll zoomOnScroll={false} preventScrolling={false}>
      <Background variant={BackgroundVariant.Lines} gap={40} size={0.4} color="var(--graph-grid)" />
    </ReactFlow>
    
    <div className="graph-controls" aria-label="Graph controls"><button className="icon-button" type="button" aria-label="Zoom out" title="Zoom out" onClick={() => instance?.zoomOut({ duration: reduceMotion() ? 0 : 160 })}><Icon name="minus" /></button><span>{zoom}%</span><button className="icon-button" type="button" aria-label="Zoom in" title="Zoom in" onClick={() => instance?.zoomIn({ duration: reduceMotion() ? 0 : 160 })}><Icon name="plus" /></button><i /><button className="icon-button" type="button" aria-label="Fit graph to view" title="Fit to view" onClick={fit}><Icon name="fit" /></button></div>
  </div>;
}

function Legend() {
  return <div className="graph-legend"><span><i className="legend-line" />Documented</span><span><i className="legend-line inferred" />Inferred</span><span><i className="legend-line hypothesis" />Proposed</span></div>;
}

export default function Graph({ report, evidence, onSelect, dark, onExploreModules }: { report: Report; evidence: Evidence[]; onSelect: (id: string) => void; dark: boolean; onExploreModules?:(paths:string[])=>void }) {
  const hasModules=report.nodes.some(node=>node.kind==="module_group");
  const [scope,setScope]=useState<"all"|"system"|"implementation">("all");
  const displayReport = useMemo(() => {
    const scoped=hasModules&&scope!=="all"?report.nodes.filter(node=>scope==="system"?node.kind!=="module_group":node.kind==="module_group"||node.context==="repository"):report.nodes;
    const ids=new Set(scoped.map(node=>node.id));
    return { ...report,edges:report.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target)), nodes: scoped.map((node, index) => {
      if (node.lane) return node;
      const layout = { lane: node.context || "Application", x: node.position?.x??Math.floor(index / 4) * 340, y: node.position?.y??(index % 4) * 220 + 50 };
      return { ...node, lane: layout.lane, position: { x: layout.x, y: layout.y } };
    }) };
  }, [report,scope,hasModules]);
  const [expanded, setExpanded] = useState(false), [focused, setFocused] = useState(""), [hovered, setHovered] = useState(""), [activeClaim, setActiveClaim] = useState("");
  const [query, setQuery] = useState(""), [lane, setLane] = useState("all"),[focusOnly,setFocusOnly]=useState(false);
  const close = useCallback(() => setExpanded(false), []);
  const select = useCallback((claim: string, component: string) => { setFocused(component); setActiveClaim(claim); if (!expanded) onSelect(claim); }, [expanded, onSelect]);
  const claim = report.claims.find(item => item.id === activeClaim);
  const lanes = [...new Set(displayReport.nodes.map(node => node.lane).filter((value): value is string => !!value))];
  const mapReport=useMemo(()=>{if(!focusOnly||!focused)return displayReport;const ids=new Set([focused]);for(const edge of displayReport.edges){if(edge.source===focused||edge.target===focused){ids.add(edge.source);ids.add(edge.target);}}return {...displayReport,nodes:displayReport.nodes.filter(node=>ids.has(node.id)),edges:displayReport.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target))};},[displayReport,focused,focusOnly]);
  const canvasProps = { report: mapReport, dark, focused, hovered, setHovered, inspect: select };
  return <section className="architecture-map">
    <div className="map-header"><div><h2>Architecture constellation</h2><p>{report.nodes.length ? `${report.nodes.length} components, ${report.edges.length} relationships` : "The selected assessment did not establish a service topology."}</p></div><button className="icon-button expand-button" aria-label="Expand architecture graph" title="Expand graph" onClick={() => setExpanded(true)}><Icon name="expand" /></button></div>
    {hasModules&&<div className="map-scope lane-filter" aria-label="Map scope">{(["all","system","implementation"] as const).map(value=><button key={value} aria-pressed={scope===value} onClick={()=>{setScope(value);setLane("all");setFocused("");setActiveClaim("");}}><Icon name={value==="implementation"?"code":"graph"}/>{value==="all"?"All":value==="system"?"System":"Code"}</button>)}<span>{displayReport.nodes.length} components · {displayReport.edges.length} relationships</span></div>}
    <div className="map-caption"><Legend /><button className="quiet-button" onClick={() => { setFocused(""); setActiveClaim(""); }} disabled={!focused}>Clear selection</button></div>
    {report.nodes.length>0&&<div className="graph-filterbar"><label className="component-search"><Icon name="search"/><input aria-label="Search architecture components" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Find a component"/></label><SelectField compact label="Architecture layer" value={lane} onChange={setLane} options={[{value:"all",label:"All layers"},...lanes.map(value=>({value,label:value}))]}/><button className="quiet-button map-focus-toggle" aria-pressed={focusOnly} disabled={!focused} onClick={()=>setFocusOnly(value=>!value)}><Icon name="branch"/>Isolate focus</button></div>}
    {report.nodes.length?<Canvas {...canvasProps} query={query} lane={lane} />:<div className="empty-state"><Icon name="graph"/><h3>No established components</h3><p>{report.run?.failures?.length?"Processing stopped before a component map was established. Review the analysis record and resume the saved sources.":report.technologies.length?"Technology references were found, but the selected sources do not identify separate application components.":"Review the source inventory or add technical declarations to establish a component map."}</p></div>}
    {!expanded&&focused&&<div className="selected-component-toolbar"><span>{report.nodes.find(node=>node.id===focused)?.label}</span>{onExploreModules&&report.nodes.find(node=>node.id===focused)?.module_paths?.length?<button className="quiet-button" onClick={()=>onExploreModules(report.nodes.find(node=>node.id===focused)!.module_paths!)}>Explore modules<Icon name="arrow"/></button>:null}<button className="quiet-button" onClick={()=>{setFocused("");setActiveClaim("");}}>Clear focus<Icon name="close"/></button></div>}
    
    <details className="component-directory"><summary>Directory</summary><div>{report.nodes.map(node => <button className="directory-item" key={node.id} onClick={() => select(node.claim_id, node.id)}><span>{node.label}</span><small>{classificationLabel(node.classification)}</small><Icon name="chevron" /></button>)}</div><div>{report.edges.map(edge => <button className="directory-item" key={edge.id} onClick={() => select(edge.claim_id, edge.source)}><span>{report.nodes.find(node => node.id === edge.source)?.label} → {report.nodes.find(node => node.id === edge.target)?.label}</span><small>{edge.label}</small><Icon name="chevron" /></button>)}</div></details>
    {expanded && <Dialog close={close} className="graph-dialog">
      <header className="expanded-map-header"><div><span className="eyebrow">Architecture</span><DialogTitle>Architecture constellation</DialogTitle></div><div><span className="expanded-count">{report.nodes.length} components</span><button className="icon-button" aria-label="Close expanded graph" title="Close expanded graph" onClick={close}><Icon name="collapse" /></button></div></header>
      <div className="expanded-map-toolbar"><div className="component-search"><Icon name="search" /><input aria-label="Find a component" value={query} onChange={event => setQuery(event.target.value)} placeholder="Find a component" />{query && <button className="icon-button" aria-label="Clear component search" onClick={() => setQuery("")}><Icon name="close" /></button>}</div><SelectField compact label="Component layer" value={lane} onChange={setLane} options={[{value:"all",label:"All layers"},...lanes.map(value=>({value,label:value}))]}/><button className="quiet-button map-focus-toggle" aria-pressed={focusOnly} disabled={!focused} onClick={()=>setFocusOnly(value=>!value)}><Icon name="branch"/>Isolate focus</button></div>
      <div className="expanded-map-body"><div className="expanded-canvas"><Canvas {...canvasProps} query={query} lane={lane}/></div>{claim && <aside className="graph-detail-panel"><div className="graph-detail-heading"><h3>Evidence</h3><button className="icon-button" aria-label="Close graph details" onClick={() => { setActiveClaim(""); setFocused(""); }}><Icon name="close" /></button></div><ClaimDetails claim={claim} evidence={evidence} />{report.nodes.find(node=>node.id===focused)?.module_paths?.length&&onExploreModules?<button className="quiet-button" onClick={()=>{onExploreModules(report.nodes.find(node=>node.id===focused)!.module_paths!);setExpanded(false);}}>Explore {report.nodes.find(node=>node.id===focused)!.module_paths!.length} modules<Icon name="arrow"/></button>:null}{report.nodes.find(node=>node.id===focused)?.source_paths?.length? <details><summary>Implementation files</summary>{report.nodes.find(node=>node.id===focused)!.source_paths!.map(path=><p key={path}><code>{path}</code></p>)}{report.nodes.find(node=>node.id===focused)!.claim_ids?.filter(id=>id!==claim.id).map(id=><button className="quiet-button" key={id} onClick={()=>setActiveClaim(id)}>Inspect another declaration<Icon name="arrow"/></button>)}</details>:null}</aside>}</div>
      <div className="expanded-map-footer"><Legend /><span>{`${displayReport.nodes.length} components, ${displayReport.edges.length} relationships`}</span></div>
    </Dialog>}
  </section>;
}
