"use client";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { loadBrandAssets } from "@/components/brand";
type ThemeTransition={finished:Promise<void>;skipTransition:()=>void};
type ThemeDocument=Document & {startViewTransition?:((update:()=>void)=>ThemeTransition)};
export function useAppearance() {
  const [dark,setDark]=useState(()=>typeof document!=="undefined"&&document.documentElement.dataset.theme==="dark");
  const [hasIcon,setHasIcon]=useState(false);
  const transition=useRef<ThemeTransition|null>(null),timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>{void loadBrandAssets().then(setHasIcon).catch(()=>{});return()=>{if(timer.current)clearTimeout(timer.current);transition.current?.skipTransition();};},[]);
  useEffect(()=>{document.documentElement.dataset.themeReady="true";},[]);
  function toggleTheme(){
    const root=document.documentElement,next=root.dataset.theme!=="dark";
    try{localStorage.setItem("prisma-theme",next?"dark":"light");}catch{}
    transition.current?.skipTransition();transition.current=null;if(timer.current)clearTimeout(timer.current);
    const change=()=>{root.dataset.theme=next?"dark":"light";flushSync(()=>setDark(next));};
    const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;
    const doc=document as ThemeDocument;
    if(doc.startViewTransition&&!reduced){
      root.dataset.themeSwitching="snapshot";
      const current=doc.startViewTransition(change);transition.current=current;
      void current.finished.catch(()=>{}).finally(()=>{if(transition.current===current){delete root.dataset.themeSwitching;transition.current=null;}});
    }else{
      root.dataset.themeSwitching=reduced?"instant":"fallback";change();
      timer.current=setTimeout(()=>{delete root.dataset.themeSwitching;},reduced?0:360);
    }
  }
  return {dark,hasIcon,toggleTheme};
}
