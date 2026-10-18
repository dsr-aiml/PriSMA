const {readFileSync}=require("node:fs");
const {resolve}=require("node:path");
const {test}=require("node:test");
const assert=require("node:assert/strict");
const ts=require("typescript"),output={};
const code=ts.transpileModule(readFileSync(resolve(__dirname,"../lib/api.ts"),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function("exports",code)(output);

test("folder MIME overrides the JSON default once and preserves the body",async()=>{
  const original=global.fetch,body=JSON.stringify({files:[{path:"app/main.py",data:"cHJpbnQoMSk="}]});
  try{
    global.fetch=async(url,options)=>{
      assert.equal(url,"/api/sources/preview?filename=app");
      assert.equal(new Headers(options.headers).get("content-type"),"application/vnd.prisma.files+json");
      assert.equal(options.body,body);
      return Response.json({retained:1});
    };
    assert.deepEqual(await output.api("/sources/preview?filename=app",{method:"POST",headers:{"content-type":"application/vnd.prisma.files+json"},body}),{retained:1});
  }finally{global.fetch=original;}
});
test("binary ZIP and document uploads reach fetch byte-for-byte",async()=>{
  const original=global.fetch,body=new Blob([new Uint8Array([0x50,0x4b,0,0xff,0xfe,0x10])]);
  try{
    global.fetch=async(_url,options)=>{
      assert.equal(new Headers(options.headers).get("content-type"),"application/octet-stream");
      assert.deepEqual([...new Uint8Array(await options.body.arrayBuffer())],[0x50,0x4b,0,0xff,0xfe,0x10]);
      return Response.json({retained:1});
    };
    await output.api("/sources/preview",{method:"POST",headers:new Headers({"CONTENT-TYPE":"application/octet-stream"}),body});
  }finally{global.fetch=original;}
});
test("JSON requests get a default MIME while GET and FormData stay unforced",async()=>{
  const original=global.fetch,types=[];
  try{
    global.fetch=async(_url,options)=>{types.push(new Headers(options.headers).get("content-type"));return Response.json({});};
    await output.api("/research/configuration");
    await output.api("/questions",{method:"POST",headers:[["x-example","value"]],body:'{"question":"How?"}'});
    await output.api("/upload",{method:"POST",body:new FormData()});
    assert.deepEqual(types,[null,"application/json",null]);
  }finally{global.fetch=original;}
});

test("successful chat deletion accepts HTTP 204 without JSON",async()=>{
 const original=global.fetch;
 try{global.fetch=async()=>new Response(null,{status:204});assert.equal(await output.api("/chats/one",{method:"DELETE"}),undefined);}
 finally{global.fetch=original;}
});
