import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
const languages={typescript:()=>import("@shikijs/langs/typescript"),javascript:()=>import("@shikijs/langs/javascript"),python:()=>import("@shikijs/langs/python"),json:()=>import("@shikijs/langs/json"),yaml:()=>import("@shikijs/langs/yaml"),toml:()=>import("@shikijs/langs/toml"),sql:()=>import("@shikijs/langs/sql"),html:()=>import("@shikijs/langs/html"),markdown:()=>import("@shikijs/langs/markdown")};
const highlighter=createHighlighterCore({themes:[import("@shikijs/themes/github-light"),import("@shikijs/themes/github-dark")],langs:[],engine:createJavaScriptRegexEngine()});
export async function highlightSource(code:string,language:string,dark:boolean){
  const lang=language as keyof typeof languages,instance=await highlighter;
  if(languages[lang]&&!instance.getLoadedLanguages().includes(lang))await instance.loadLanguage(await languages[lang]());
  return instance.codeToTokens(code,{lang:languages[lang]?lang:"text",theme:dark?"github-dark":"github-light"}).tokens;
}
