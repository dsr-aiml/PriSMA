"use client";
import { useId } from "react";

export function Brand({ hasIcon = false }: { hasIcon?: boolean }) {
  return <a className="brand" href="/" aria-label="PriSMA home">
    {hasIcon && <img className="brand-icon" src="/icon.png" width={48} height={48} alt="" aria-hidden="true" />}
    <span className="wordmark">PriSMA</span>
  </a>;
}

export function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  const id = "theme-mask-" + useId().replaceAll(":", "");
  return <button className="theme-toggle" type="button" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} aria-pressed={dark} title={dark ? "Switch to light theme" : "Switch to dark theme"} onClick={onToggle}>
    <svg className="theme-symbol" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <defs><mask id={id}><rect width="32" height="32" fill="white" /><circle className="moon-cutout" cx="30" cy="16" r="7" fill="black" /></mask></defs>
      <circle className="theme-core" cx="16" cy="16" r="7" fill="currentColor" mask={`url(#${id})`} />
      <g className="sun-rays" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M16 2v3m0 22v3M2 16h3m22 0h3M6.1 6.1l2.1 2.1m15.6 15.6 2.1 2.1M6.1 25.9l2.1-2.1M23.8 8.2l2.1-2.1" />
      </g>
    </svg>
  </button>;
}

let brandAssets: Promise<boolean>|null = null;
export function loadBrandAssets(): Promise<boolean> {
  if (!brandAssets) brandAssets = initializeBrandAssets().catch(error=>{brandAssets=null;throw error;});
  return brandAssets;
}
async function initializeBrandAssets(): Promise<boolean> {
  const response = await fetch("/brand-assets", { cache: "no-store" });
  if (!response.ok) return false;
  const assets: { icon: boolean; monoFonts: { url: string; weight: string }[];headingFont?:{url:string;weight:string}|null } = await response.json();
  await Promise.allSettled(assets.monoFonts.map(async asset => {
    const font = new FontFace("PriSMA Mono", `url("${asset.url}")`, { weight: asset.weight, display: "swap" });
    await font.load(); document.fonts.add(font);
  }));
  if (assets.headingFont) {
    const font = new FontFace("PriSMA Heading", `url("${assets.headingFont.url}")`, {weight:assets.headingFont.weight,display:"swap"});
    try { await font.load(); document.fonts.add(font); } catch { /* Readable Geist fallback. */ }
  }
  if (assets.icon) {
    const link = document.createElement("link"); link.rel = "icon"; link.href = "/icon.png"; document.head.append(link);
  }
  return assets.icon;
}
