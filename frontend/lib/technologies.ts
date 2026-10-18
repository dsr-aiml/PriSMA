import type { Report } from "./api";

export type TechnologyScope="application"|"tooling"|"all";
type Technology=Report["technologies"][number];
type Role={key:string;label:string;priority:number;application:boolean};
const roles:Record<string,Role>={
  source_language:{key:"languages",label:"Languages",priority:0,application:true},
  shipped_application:{key:"observed",label:"Client runtime",priority:1,application:true},
  client_asset_marker:{key:"observed",label:"Client runtime",priority:1,application:true},
  observed_delivery:{key:"delivery",label:"Delivery",priority:2,application:true},
  page_generator:{key:"generator",label:"Generator",priority:3,application:true},
  source_usage:{key:"imports",label:"Imported",priority:4,application:true},
  dependencies:{key:"dependencies",label:"Dependencies",priority:5,application:true},
  container_images:{key:"containers",label:"Container images",priority:6,application:true},
  optionalDependencies:{key:"optional",label:"Optional",priority:7,application:true},
  peerDependencies:{key:"peers",label:"Peer dependencies",priority:8,application:true},
  devDependencies:{key:"development",label:"Development",priority:20,application:false},
  build_tool:{key:"build",label:"Build",priority:21,application:false},
  test_dependencies:{key:"tests",label:"Tests",priority:22,application:false},
  third_party:{key:"third-party",label:"Third-party sources",priority:23,application:false},
};
function describe(group:string):Role{
  if(group.startsWith("documented_"))return {key:"documented",label:"Documented",priority:9,application:true};
  return roles[group]??{key:"references",label:"References",priority:30,application:false};
}
export type TechnologyEntry={technology:Technology;claimId:string;versions:string[];declarations:number};
export type TechnologyGroup={key:string;label:string;priority:number;entries:TechnologyEntry[]};

export function technologyGroups(technologies:Technology[],scope:TechnologyScope,query=""):TechnologyGroup[]{
  const groups=new Map<string,TechnologyGroup>(),seen=new Set<string>();
  const needle=query.trim().toLocaleLowerCase();
  for(const technology of technologies){
    if(seen.has(technology.id)||!technology.name.toLocaleLowerCase().includes(needle))continue;
    const declarations=technology.declarations?.length?technology.declarations:[{group:technology.category,version:"",claim_id:technology.claim_id}];
    const eligible=declarations.filter(d=>scope==="all"||describe(d.group).application===(scope==="application"));
    if(!eligible.length)continue;
    const chosen=[...eligible].sort((a,b)=>describe(a.group).priority-describe(b.group).priority)[0];
    const role=describe(chosen.group);
    const versions=[...new Set(eligible.filter(d=>describe(d.group).key===role.key).map(d=>d.version).filter(Boolean))];
    if(!versions.length&&role.application)versions.push(...new Set(eligible.filter(d=>describe(d.group).application).map(d=>d.version).filter(Boolean)));
    const group=groups.get(role.key)??{key:role.key,label:role.label,priority:role.priority,entries:[]};
    group.entries.push({technology,claimId:chosen.claim_id||technology.claim_id,versions,declarations:new Set(eligible.map(d=>d.claim_id)).size});
    groups.set(role.key,group);seen.add(technology.id);
  }
  return [...groups.values()].sort((a,b)=>a.priority-b.priority).map(group=>({...group,entries:group.entries.sort((a,b)=>a.technology.name.localeCompare(b.technology.name))}));
}
