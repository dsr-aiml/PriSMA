export type SourceRange={start:number;end:number};

// Saved scanner and citation offsets count Unicode characters, not UTF-16 units.
export function sourceRange(text:string,range:SourceRange):SourceRange|null {
  if(!Number.isInteger(range.start)||!Number.isInteger(range.end)||range.start<0||range.end<=range.start)return null;
  let point=0,offset=0,start:number|undefined;
  while(offset<=text.length){
    if(point===range.start)start=offset;
    if(point===range.end)return start===undefined?null:{start,end:offset};
    if(offset===text.length)break;
    offset+=(text.codePointAt(offset)??0)>65535?2:1;point++;
  }
  return null;
}

export function sourceWindow(starts:number[],offset:number,window=20000,lines=80){
  let lo=0,hi=starts.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(starts[mid]<=offset)lo=mid+1;else hi=mid;}
  const page=Math.floor(Math.max(0,lo-1)/lines);
  return {page,segment:Math.floor(Math.max(0,offset-(starts[page*lines]??0))/window)};
}
