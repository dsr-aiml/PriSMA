export function searchScore(text:string,query:string):number{
  const normalize=(value:string)=>value.normalize("NFKD").replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase().replace(/[_/.-]+/g," ");
  const haystack=normalize(text),needle=normalize(query).trim();
  if(!needle)return 1;
  if(haystack===needle)return 100;
  if(haystack.startsWith(needle))return 85;
  if(haystack.includes(needle))return 70;
  const words=needle.split(/\s+/),tokens=haystack.split(/\s+/);
  if(words.every(word=>tokens.some(token=>token.startsWith(word))))return 55;
  if(words.every(word=>haystack.includes(word)))return 40;
  return 0;
}
export const reportSections=[
  {id:"overview",label:"Overview",keywords:"summary assessment coverage",icon:"layers"},
  {id:"insights",label:"Insights",keywords:"findings evidence matrix conflicts",icon:"insight"},
  {id:"architecture",label:"Architecture",keywords:"graph constellation components implementation",icon:"graph"},
  {id:"repository",label:"Repository",keywords:"code modules files imports dependency",icon:"branch"},
  {id:"api",label:"API",keywords:"contracts endpoints routes operations",icon:"server"},
  {id:"data",label:"Data model",keywords:"schemas entities fields types",icon:"database"},
  {id:"technologies",label:"Technologies",keywords:"stack frameworks language dependencies",icon:"code"},
  {id:"features",label:"Capabilities",keywords:"features pricing commercial availability",icon:"grid"},
  {id:"sources",label:"Sources",keywords:"inventory evidence documents",icon:"document"},
  {id:"questions",label:"Research query",keywords:"ask question answers query engine",icon:"search"},
  {id:"activity",label:"Activity",keywords:"processing history logs worker coverage",icon:"activity"}
] as const;
