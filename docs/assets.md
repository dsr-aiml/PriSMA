# Public assets

The Next.js public directory is frontend/public/ inside your existing project folder. It already exists in the update. Its contents are served from the site's root URL. Place user assets there before rebuilding the frontend.

| Local project path | Use | Required? |
| --- | --- | --- |
| frontend/public/icon.png | Brand icon and browser favicon; transparent square PNG suggested, 256px or larger | Optional; supplied by you |
| frontend/public/fonts/SF-Mono-Regular.otf | Technical text at regular weight | Optional; use your existing file |
| frontend/public/fonts/SF-Mono-Medium.otf | Technical text at medium weight | Optional; use your existing file |
| frontend/public/assets/ | Future user-provided illustrations or screenshots | Empty reserved directory |

The same SF Mono filenames also accept .woff2, .woff, or .ttf; the loader prefers webfont formats when available. Use files available to you for web embedding. Missing or invalid optional fonts fall back to bundled Geist Mono.

Orbitron, Geist Sans, and Geist Mono are already self-hosted by the application. All interface, graph, and theme icons are coded SVGs. No purchased artwork, decorative background image, or external asset download is required for this interface.

After adding or replacing assets:

```bash
sudo docker compose up --build -d frontend
```

Refresh the browser afterwards. Updates preserve user-added assets and .env. The upload package does not contain your private icon or optional font binaries. Files from an earlier display-font choice can stay in public/fonts/ but are no longer loaded.
