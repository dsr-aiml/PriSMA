# PriSMA visual identity

Product spelling is PriSMA, including the exact-case wordmark. Use the user's optional frontend/public/icon.png when present. Without it, the wordmark stands alone.

| Role | Typeface and treatment |
| --- | --- |
| Wordmark | Self-hosted Orbitron, weight 600, exact PriSMA case |
| Primary display heading | Orbitron, uppercase, weight 700–750 |
| Secondary display heading | Orbitron, uppercase, weight 400, muted neutral tone |
| Secondary headings | User-owned Oxanium variable font, weight 450–550; Geist fallback |
| Body and controls | Self-hosted Geist Sans, mostly weight 350–500 |
| Fields and placeholders | Geist Sans, neutral grey, regular/light weight, 16–17px |
| URLs, routes, resource fields | Optional SF Mono; bundled Geist Mono fallback |

Orbitron is provided by the pinned @fontsource-variable/orbitron package and loaded locally. Its supported weight range starts at 400, which is the lightest secondary display treatment. No external font request is made at runtime. The bundled license is in docs/licenses/orbitron.txt.

The header is a compact aligned row. The supplied brand icon renders at 48px on desktop and 40px in compact workspace headers, 60% larger than the earlier slots, using object-fit containment. The borderless theme control occupies the far right. In dark mode, its crescent opens toward the top-right using a -45-degree SVG rotation. Icon and surface transitions follow reduced-motion preferences; theme initialization precedes client rendering.

The light landing page uses the original cool white background (#f7f8fa), soft cool grey story surface (#f0f2f5), white header and fields, and subtle borders (#e1e5eb). These variables are scoped to the landing shell. Workspace surfaces and the dark palette have independent values.

Processing history is a vertical chronological timeline. Neutral stage icons connect along one track; consecutive events in the same stage share a heading, with each original message and timestamp retained. If a stage recurs later it forms another group. The list expands while a report is processing and can be opened after completion. At narrow widths, timestamps stack under their messages.

Use quiet visible sample provenance, concise expert copy, neutral status wording, restrained borders, and generous separation between content groups. Do not add decorative colored status dots, slash-separated slogans, generic select menus, padded counters, or repeated sample/completion badges. Model coverage uses custom radio controls. Buttons use a consistent aligned label and directional icon, with restrained interaction motion.

The constellation uses explicit source/target handles, grouped architectural layers, routed connections, directional arrows, and distinct line styles for documented, inferred, and proposed paths. Selecting a component highlights its connections and dims unrelated components. Labels appear for focused or hovered connections. The expand action opens a 90vw × 90dvh modal (94vw × 92dvh on narrow screens), with search, layer controls, in-place evidence assessment, custom zoom/fit controls, keyboard dismissal, focus restoration, background inertness, and scroll locking.

Existing saved reports continue to render without the new optional lane/description properties. The more extensive Atlas model appears in newly created investigations; old findings are never silently rewritten.

## 0.8.4 surfaces, controls and landing motion

`frontend/app/themes.css` owns the shared palette. Dark mode uses the approved desaturated slate-cyan endpoints #7A9190 and #6B8B8C over black and graphite. Light mode carries a slight cool tint, with darker slate-cyan text for contrast. Summary numbers use a quiet gradient; ordinary reading text stays solid.

`frontend/app/controls.css` owns the common control treatment. Filled actions use small tonal gradients and a short soft shadow. Secondary controls use an even muted border; selected switches use quiet value separation with no bright bottom rail or embossed edge. Keyboard focus and selected/disabled states remain visible. The button rules do not apply to the decorative landing illustration.

`frontend/app/landing-scene.css` restores the approved pre-0.8.3 scene: three lifted planes, mouse-tracked bevel perspective, entry movement, flowing analysis paths and subtle sheen. Its component is recovered exactly from the 0.8.2 source. It remains decorative, pauses when hidden and honors reduced motion. The functional architecture map remains 2D.

Put the optional user-owned `Oxanium-VariableFont_wght.ttf` in `frontend/public/fonts/`. The asset endpoint checks existence before loading it, supports variable weights 200–800, and falls back to Geist without a missing-font request. Overlay archives never modify font or logo files. Orbitron remains for the wordmark and main displays; Oxanium handles smaller headings and captions; chats, detailed reading and inputs retain Geist.
