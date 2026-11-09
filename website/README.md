# EnvGuard CI marketing website

A lightweight, static GitHub Pages website for the [EnvGuard CI](https://github.com/zgcharaf/ENV-Guard) open-source project.

## Local preview

Open `website/index.html` in a browser, or run:

```bash
python -m http.server 8000 --directory website
```

Then open http://localhost:8000/.

No npm, Node, CDN, trackers, or backend are needed. The scenario switcher is **illustrative and local**; it does not execute EnvGuard or send logs anywhere.

## Deploy with GitHub Pages

The repository includes `.github/workflows/pages.yml`. To activate:

1. In the repository, navigate to **Settings → Pages**.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
3. In **Actions**, run the **Deploy EnvGuard website** workflow, or push changes to `website/`.
4. After the deployment completes, visit https://zgcharaf.github.io/ENV-Guard/.

The site intentionally avoids promises about PyPI availability, enterprise certification, or unattended auto-remediation.

## Modify

Edit `index.html`, `styles.css`, or `app.js`. The URL and GitHub paths are configured for `zgcharaf/ENV-Guard`. Update both the public URL and social metadata if the repository is moved.
