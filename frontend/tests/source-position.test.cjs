const {readFileSync}=require('node:fs');
const {resolve}=require('node:path');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('typescript'),output={};
const code=ts.transpileModule(readFileSync(resolve(__dirname,'../lib/source-position.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function('exports',code)(output);

test('scanner locations survive emoji and distinguish reused bundled names',()=>{
  const text='// 🧭\nfunction i(){return 1;} function i(){return 2;}',points=Array.from(text);
  const first=points.join('').indexOf('function');
  const firstPoint=Array.from(text.slice(0,first)).length;
  const secondPoint=points.join('').lastIndexOf('function')-1;
  const a=output.sourceRange(text,{start:firstPoint,end:firstPoint+23});
  const b=output.sourceRange(text,{start:secondPoint,end:secondPoint+23});
  assert.equal(text.slice(a.start,a.end),'function i(){return 1;}');
  assert.equal(text.slice(b.start,b.end),'function i(){return 2;}');
  assert.notEqual(a.start,b.start);
});

test('invalid and stale ranges cannot select unrelated text',()=>{
  for(const range of [{start:-1,end:2},{start:1,end:1},{start:0,end:99},{start:0.5,end:2},{start:NaN,end:2}])assert.equal(output.sourceRange('sample',range),null);
});

test('deep declarations in a minified bundle open their bounded segment',()=>{
  assert.deepEqual(output.sourceWindow([0,65001],54000),{page:0,segment:2});
  assert.deepEqual(output.sourceWindow(Array.from({length:162},(_,i)=>i*100),8502),{page:1,segment:0});
});
