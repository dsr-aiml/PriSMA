"use client";
import { useState } from "react";
import { type Evidence } from "@/lib/api";
import { SourceReader } from "@/components/source-reader";
export function SourceContent({source,label="Document content"}:{source:Evidence;label?:string}) {
  const [open,setOpen]=useState(false);
  return <details onToggle={event=>setOpen(event.currentTarget.open)}><summary>{label}</summary>{open&&<SourceReader source={source} citations={[]}/>}</details>;
}
