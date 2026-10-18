/* Parse supplied text only. No imported configuration or source is evaluated. */
const fs = require('node:fs');
const ts = require('typescript');
const MAX_ROWS = 1600;
function scan(file) {
  const kind = /\.tsx$/i.test(file.path) ? ts.ScriptKind.TSX : /\.jsx$/i.test(file.path) ? ts.ScriptKind.JSX : /\.[cm]?ts$/i.test(file.path) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
  const tree = ts.createSourceFile(file.path, file.content, ts.ScriptTarget.Latest, true, kind);
  const virtualName='/virtual/unit.'+(kind===ts.ScriptKind.TSX?'tsx':kind===ts.ScriptKind.TS?'ts':kind===ts.ScriptKind.JSX?'jsx':'js');
  tree.fileName=virtualName;
  const program=ts.createProgram([virtualName],{noLib:true,noResolve:true,allowJs:true},{getSourceFile:name=>name===virtualName?tree:undefined,getDefaultLibFileName:()=>'',writeFile:()=>{},getCurrentDirectory:()=>'/virtual',getDirectories:()=>[],fileExists:name=>name===virtualName,readFile:name=>name===virtualName?file.content:undefined,getCanonicalFileName:name=>name,useCaseSensitiveFileNames:()=>true,getNewLine:()=> '\n'});
  const checker=program.getTypeChecker();
  // TypeScript offsets are UTF-16; saved citations use Unicode code points.
  const offsets = new Uint32Array(file.content.length + 1);
  let points = 0;
  for (let i=0;i<file.content.length;) {
    const width = file.content.codePointAt(i)>0xffff ? 2 : 1;
    offsets[i] = points; if(width===2) offsets[i+1] = points;
    i+=width; offsets[i]=++points;
  }
  const result = {path:file.path, parser:'typescript-5.9.3', status:'parsed', imports:[], symbols:[], schemas:[], calls:[], routes:[], mounts:[], resources:[], diagnostics:[], truncated:false};
  const span = node => ({start:offsets[node.getStart(tree)], end:offsets[node.end]});
  function add(key,row){if(result[key].length<MAX_ROWS) result[key].push(row);else result.truncated=true;}
  const literal = node => node && ts.isStringLiteralLike(node) ? node.text : null;
  const callName = node => ts.isIdentifier(node) ? node.text : ts.isPropertyAccessExpression(node) ? node.getText(tree) : '';
  function visit(node) {
    if(ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      const name=literal(node.moduleSpecifier);
      if(name!==null){const bindings=[]; const clause=node.importClause;
        if(clause?.name)bindings.push({local:clause.name.text, imported:'default'});
        const named=clause?.namedBindings;
        if(named && ts.isNamedImports(named))for(const element of named.elements)bindings.push({local:element.name.text,imported:element.propertyName?.text||element.name.text});
        else if(named && ts.isNamespaceImport(named)) bindings.push({local:named.name.text,imported:'*'});
        add('imports',{name,bindings,type_only:!!clause?.isTypeOnly,reexport:ts.isExportDeclaration(node),...span(node)});
      }
    }
    if(ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
      const name=literal(node.moduleReference.expression);if(name!==null)add('imports',{name,bindings:[{local:node.name.text,imported:'*'}],...span(node)});
    }
    if(ts.isFunctionDeclaration(node)||ts.isClassDeclaration(node)||ts.isInterfaceDeclaration(node)||ts.isTypeAliasDeclaration(node)||ts.isEnumDeclaration(node)) {
      if(node.name)add('symbols',{name:node.name.text,kind:ts.SyntaxKind[node.kind],exported:!!node.modifiers?.some(x=>x.kind===ts.SyntaxKind.ExportKeyword),...span(node)});
    }
    if(ts.isInterfaceDeclaration(node)||(ts.isTypeAliasDeclaration(node)&&ts.isTypeLiteralNode(node.type))) {
      const members=ts.isInterfaceDeclaration(node)?node.members:node.type.members;
      const fields=members.filter(member=>ts.isPropertySignature(member)&&member.type&&(ts.isIdentifier(member.name)||ts.isStringLiteral(member.name))).slice(0,150).map(member=>({name:member.name.text,type:member.type.getText(tree).slice(0,120),required:!member.questionToken,...span(member)}));
      add('schemas',{name:node.name.text,kind:ts.isInterfaceDeclaration(node)?'interface':'type_literal',fields,...span(node)});
    }
    if(ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && (ts.isArrowFunction(node.initializer)||ts.isFunctionExpression(node.initializer))) add('symbols',{name:node.name.text,kind:'Function',...span(node)});
    if(ts.isCallExpression(node)||ts.isNewExpression(node)) {
      const args=node.arguments||[], name=callName(node.expression), first=literal(args[0]);
      if((name==='require'||node.expression.kind===ts.SyntaxKind.ImportKeyword) && first!==null){
        let bindings=[];if(ts.isVariableDeclaration(node.parent)){
          if(ts.isIdentifier(node.parent.name))bindings=[{local:node.parent.name.text,imported:'*'}];
          else if(ts.isObjectBindingPattern(node.parent.name))bindings=node.parent.name.elements.filter(x=>ts.isIdentifier(x.name)).map(x=>({local:x.name.text,imported:x.propertyName?.getText(tree)||x.name.text}));
        }add('imports',{name:first,bindings,dynamic:node.expression.kind===ts.SyntaxKind.ImportKeyword,...span(node)});
      }
      let root=node.expression;while(ts.isPropertyAccessExpression(root)||ts.isElementAccessExpression(root))root=root.expression;
      const symbol=ts.isIdentifier(root)?checker.getSymbolAtLocation(root):undefined;
      const imported=!!symbol?.declarations?.some(declaration=>ts.isImportSpecifier(declaration)||ts.isImportClause(declaration)||ts.isNamespaceImport(declaration)||ts.isImportEqualsDeclaration(declaration)||(ts.isVariableDeclaration(declaration)&&declaration.initializer&&ts.isCallExpression(declaration.initializer)&&declaration.initializer.expression.getText(tree)==='require')||(ts.isBindingElement(declaration)&&ts.isVariableDeclaration(declaration.parent.parent)&&declaration.parent.parent.initializer&&ts.isCallExpression(declaration.parent.parent.initializer)&&declaration.parent.parent.initializer.expression.getText(tree)==='require'));
      let reference=null;
      for(const declaration of symbol?.declarations||[]){let owner=declaration;while(owner.parent&&!ts.isImportDeclaration(owner)&&!ts.isVariableDeclaration(owner))owner=owner.parent;if(ts.isImportDeclaration(owner))reference=literal(owner.moduleSpecifier);else if(ts.isVariableDeclaration(owner)&&owner.initializer&&ts.isCallExpression(owner.initializer)&&owner.initializer.expression.getText(tree)==='require')reference=literal(owner.initializer.arguments[0]);}
      if(name)add('calls',{name:name.slice(0,240),imported_binding:imported,reference,construct:ts.isNewExpression(node),...span(node)});
      if(ts.isPropertyAccessExpression(node.expression)){
        const method=node.expression.name.text.toUpperCase(),receiver=node.expression.expression.getText(tree);
        if(['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'].includes(method)&&first?.startsWith('/')) add('routes',{method,path:first,receiver,handler:args[1]?callName(args[1]):'',...span(node)});
        if(method==='USE'&&first?.startsWith('/')&&args[1])add('mounts',{prefix:first,router:callName(args[1]),receiver,...span(node)});
      }
      if((name==='fetch'||name==='axios'||/^axios\.(get|post|put|patch|delete|head|options)$/.test(name))&&first!==null&&/^(https?:\/\/|\/)/.test(first))add('resources',{url:first,operation:name,...span(node)});
    }
    ts.forEachChild(node,visit);
  }
  for(const diagnostic of tree.parseDiagnostics.slice(0,12))result.diagnostics.push({message:ts.flattenDiagnosticMessageText(diagnostic.messageText,' '),offset:offsets[diagnostic.start||0]});
  if(result.diagnostics.length)result.status='partial';
  visit(tree);return result;
}
try{
  const packet=JSON.parse(fs.readFileSync(0,'utf8'));
  if(!Array.isArray(packet.files)||packet.files.length>40)throw new Error('Scanner packet exceeds its file budget');
  process.stdout.write(JSON.stringify({version:'syntax-scanners-7',files:packet.files.map(file=>{try{return scan(file);}catch{return {path:file.path,parser:"typescript-5.9.3",status:"unavailable",imports:[],symbols:[],schemas:[],calls:[],routes:[],mounts:[],resources:[],diagnostics:[{message:"Source syntax exceeded scanner handling limits."}],truncated:false};}})}));
}catch(error){process.stderr.write('Static syntax scan failed: '+String(error.message).slice(0,200));process.exitCode=1;}
