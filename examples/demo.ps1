$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'src'
py -m envguard_ci --version
py -m envguard_ci diff --baseline tests/fixtures/baseline.json --current tests/fixtures/package_missing.json
py -m envguard_ci graph --snapshot tests/fixtures/baseline.json
