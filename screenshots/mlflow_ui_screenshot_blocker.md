Generated at: 2026-05-31 23:20:36 MSK

# MLflow UI screenshot blocker

- target: `http://localhost:15000`
- HTTP check: `200`
- blocker: no project Playwright setup, no `playwright` binary, and no browser binary in PATH.
- local rule: `$playwright-ui-test` says not to install Playwright, browser binaries, npm packages, or Python browser packages without direct approval.
- substitute evidence: `reports/registry_demo.md` records run ids, model versions, aliases, compose status, and API checks.
