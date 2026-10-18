import type { Metadata } from "next";
import { MotionProvider } from "@/components/motion-provider";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "@fontsource-variable/orbitron";
import "@xyflow/react/dist/style.css";
import "./globals.css";
import "./research.css";
import "./workspace-polish.css";
import "./research-refinement.css";
import "./themes.css";
import "./controls.css";
import "./landing-scene.css";
export const metadata: Metadata = {title:"PriSMA",description:"Architecture analysis from source code and public evidence."};
const initializeTheme=`try{const saved=localStorage.getItem('prisma-theme');document.documentElement.dataset.nav=localStorage.getItem('prisma:nav')||'full';document.documentElement.dataset.theme=saved||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}catch{document.documentElement.dataset.theme='light'}`;
export default function Layout({children}:{children:React.ReactNode}) {
  return <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning><head><script dangerouslySetInnerHTML={{__html:initializeTheme}}/></head><body><MotionProvider>{children}</MotionProvider></body></html>;
}
