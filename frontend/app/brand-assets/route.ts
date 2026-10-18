import { access } from "node:fs/promises";
import path from "node:path";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function exists(file: string) {
  try { await access(path.join(process.cwd(), "public", file)); return true; } catch { return false; }
}
export async function GET() {
  const monoFonts: { url: string; weight: string }[] = [];
  for (const [name, weight] of [["SF-Mono-Regular", "400"], ["SF-Mono-Medium", "500"]]) {
    for (const format of ["woff2", "woff", "otf", "ttf"]) {
      const file = `fonts/${name}.${format}`;
      if (await exists(file)) { monoFonts.push({ url: "/" + file, weight }); break; }
    }
  }
  let headingFont: {url:string;weight:string}|null = null;
  for (const file of ["fonts/Oxanium-VariableFont_wght.ttf", "fonts/Oxanium-VariableFont_wght.woff2", "Oxanium-VariableFont_wght.ttf"]) {
    if (await exists(file)) { headingFont = {url:"/"+file,weight:"200 800"}; break; }
  }
  return Response.json({ icon: await exists("icon.png"), monoFonts, headingFont }, { headers: { "Cache-Control": "no-store" } });
}
