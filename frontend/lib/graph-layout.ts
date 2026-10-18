import ELK, { type ElkNode } from "elkjs/lib/elk-api";
import type { Report } from "@/lib/api";
export type Layout={positions:Record<string,{x:number;y:number}>;routes:Record<string,{x:number;y:number}[]>};
const cache=new Map<string,Promise<Layout>>();
export function layoutGraph(report:Report,width:number,height:number){
  const ids=new Set(report.nodes.map(node=>node.id)),edges=report.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target));
  const key=JSON.stringify([width,height,report.nodes.map(n=>n.id),edges.map(e=>[e.id,e.source,e.target])]);
  const saved=cache.get(key);if(saved)return saved;
  if(report.nodes.length>600||edges.length>3500)return Promise.reject(new Error("Use the retained layout for this large map."));
  const task=(async()=>{
    const worker=new Worker(new URL("elkjs/lib/elk-worker.min.js",import.meta.url));
    const engine=new ELK({workerFactory:()=>worker});
    let timer:ReturnType<typeof setTimeout>|undefined;
    try{
      const result=await Promise.race([engine.layout<ElkNode>({id:"prisma-map",layoutOptions:{"elk.algorithm":"layered","elk.direction":"RIGHT","elk.spacing.nodeNode":"36","elk.layered.spacing.nodeNodeBetweenLayers":"136","elk.padding":"[top=48,left=32,bottom=32,right=32]"},children:report.nodes.map(node=>({id:node.id,width,height,layoutOptions:{"elk.portConstraints":"FIXED_POS"},ports:[{id:node.id+"-in",x:0,y:height/2},{id:node.id+"-out",x:width,y:height/2}]})),edges:edges.map(edge=>({id:edge.id,sources:[edge.source+"-out"],targets:[edge.target+"-in"]}))}),new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error("Layout computation reached its time limit.")),12000);})]);
      const positions:Layout["positions"]={},routes:Layout["routes"]={};
      for(const node of result.children??[])positions[node.id]={x:node.x??0,y:node.y??0};
      for(const edge of result.edges??[]){const section=edge.sections?.[0];if(section)routes[edge.id]=[section.startPoint,...(section.bendPoints??[]),section.endPoint];}
      return {positions,routes};
    }finally{if(timer)clearTimeout(timer);engine.terminateWorker();}
  })();
  cache.set(key,task);task.catch(()=>cache.delete(key));if(cache.size>12)cache.delete(cache.keys().next().value!);return task;
}
