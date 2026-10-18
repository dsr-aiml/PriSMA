const {readFileSync}=require('node:fs');
const {resolve}=require('node:path');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('typescript'),output={};
const code=ts.transpileModule(readFileSync(resolve(__dirname,'../lib/technologies.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function('exports',code)(output);
const row=(id,name,declarations)=>({id,name,category:declarations[0].group,claim_id:declarations[0].claim_id,declarations});
const declaration=(group,claim_id,version='')=>({group,claim_id,version});

test('mixed ecosystem roles stay separate and each technology appears once',()=>{
  const source=[row('a','Library A',[declaration('dependencies','manifest','>=2'),declaration('source_usage','import')]),row('b','Build B',[declaration('build_tool','build')]),row('c','Host C',[declaration('observed_delivery','header')]),row('d','Namespace D',[declaration('unclassified','ref')])];
  const app=output.technologyGroups(source,'application');
  assert.deepEqual(app.flatMap(g=>g.entries.map(e=>e.technology.name)),['Host C','Library A']);
  const library=app.find(g=>g.key==='imports').entries[0];
  assert.equal(library.claimId,'import');assert.deepEqual(library.versions,['>=2']);
  assert.deepEqual(output.technologyGroups(source,'tooling').flatMap(g=>g.entries.map(e=>e.technology.name)),['Build B','Namespace D']);
  assert.equal(output.technologyGroups(source,'all').flatMap(g=>g.entries).length,4);
});

test('documented declarations and container images remain accessible',()=>{
  const source=[row('x','Container X',[declaration('container_images','image')]),row('y','Library Y',[declaration('documented_backend','doc')])];
  assert.deepEqual(output.technologyGroups(source,'application').map(g=>g.key),['containers','documented']);
});

test('tooling versions do not become application versions',()=>{
  const source=[row('x','Library X',[declaration('source_usage','import'),declaration('devDependencies','tool','1.0')])];
  assert.deepEqual(output.technologyGroups(source,'application')[0].entries[0].versions,[]);
  assert.deepEqual(output.technologyGroups(source,'tooling')[0].entries[0].versions,['1.0']);
});

test('search is normalized, stable and preserves report data',()=>{
  const source=[row('b','Zulu',[declaration('dependencies','b')]),row('a','Alpha',[declaration('dependencies','a')])],before=JSON.stringify(source);
  assert.deepEqual(output.technologyGroups(source,'application')[0].entries.map(e=>e.technology.name),['Alpha','Zulu']);
  assert.equal(output.technologyGroups(source,'all',' ALP ')[0].entries[0].technology.name,'Alpha');
  assert.deepEqual(output.technologyGroups(source,'all','missing'),[]);
  assert.equal(JSON.stringify(source),before);
});
