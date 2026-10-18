"use client";
import { Dialog as Primitive } from "radix-ui";
import { forwardRef, useRef, type ComponentPropsWithoutRef, type ReactNode } from "react";
export const DialogTitle = forwardRef<HTMLHeadingElement, ComponentPropsWithoutRef<"h2">>(function DialogTitle(props, ref) {
  return <Primitive.Title asChild><h2 {...props} ref={ref}/></Primitive.Title>;
});
export function Dialog({children,close,className}:{children:ReactNode;close:()=>void;className:string}){
  const origin=useRef<HTMLElement|null>(typeof document!=="undefined"?document.activeElement as HTMLElement:null);
  return <Primitive.Root open onOpenChange={open=>{if(!open)close();}}><Primitive.Portal><Primitive.Overlay className="dialog-backdrop"/><Primitive.Content className={className+" prisma-dialog"} aria-describedby={undefined} onEscapeKeyDown={event=>{event.preventDefault();close();}} onCloseAutoFocus={event=>{event.preventDefault();if(origin.current?.isConnected)origin.current.focus();}}>{children}</Primitive.Content></Primitive.Portal></Primitive.Root>;
}
