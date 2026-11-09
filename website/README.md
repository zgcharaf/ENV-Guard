# EnvGuard CI — academic website

The public site for [EnvGuard CI](https://github.com/zgcharaf/ENV-Guard).

- **Homepage**: [index.html](index.html)
- **Reference manual**: [docs/index.html](docs/index.html)
- **Research and benchmarks**: [research/index.html](research/index.html)
- **Seven worked tutorials**: [tutorials/index.html](tutorials/index.html)

The design follows a restrained academic/LaTeX aesthetic: a serif document hierarchy, thin rules, numbered sections, a typeset abstract, table-based evidence, print styles, and restrained mono code samples.

## Local preview

```bash
python -m http.server 8000 --directory website
```

Open http://localhost:8000, http://localhost:8000/docs/, and http://localhost:8000/tutorials/, and http://localhost:8000/research/.

No framework, NPM, custom fonts, CDN, cookies, telemetry, or backend required.

## GitHub Pages

This repository already includes `.github/workflows/pages.yml`.

1. In **Settings → Pages**, set **Build and deployment → Source** to **GitHub Actions**.
2. Push to `main`, or use the **Deploy EnvGuard website** workflow’s manual dispatch.
3. Verify the site at https://zgcharaf.github.io/ENV-Guard/.

Pages is published from `website/`. Links use relative paths so the project subdirectory is preserved.

## Accuracy and scope

The current release is `1.0.0rc2`. Examples describe available CLI commands but are not claims that this package is on PyPI or is enterprise-production certified. The native Docker verification is a bounded import smoke, not a security sandbox.

This website is maintained alongside the source code. The source CLI's `--help` output takes precedence if options change.
