# Browser example verification

The static example in `demo/` belongs to [evaldeck](../README.md). The native program remains the reference implementation. No native runtime, network service, cloud account or model endpoint is embedded in the page.

## Reproducible checks

Run the native project's documented test/build commands, then `node --test tests-browser/*.test.mjs` and `node scripts/verify-demo.mjs` from the repository root with Node 24. Python parity uses `python3` (override with `PYTHON` if needed).

The comparison tests invoke the native implementation against the same bounded inputs rather than storing unverified expected screenshots. Other tests cover malformed inputs, bounds and the behavior stated beside each workbench. They do not establish equivalence for every possible native input or cross-browser compatibility.

## Browser acceptance

Serve only `demo/` over HTTP. Check desktop and a narrow phone viewport; keyboard focus, labels and the skip link; each preset; an edited success, failure and malformed input; stale-result messaging; recovery after failure; and JSON downloads where offered. Browser rendering and interaction checks complement the pure-function parity tests.

The page uses no inline scripts or styles, no remote assets, no browser persistence, and a `connect-src 'none'` content policy. User text is rendered with `textContent`, never HTML interpolation. Inputs are held in page memory; reload discards edits. Downloads are local files and can contain what the visitor typed.

## Publication boundary

The artifact verifier permits only the named static files in `demo/`, rejects symlinks/directories and checks module syntax and local asset references. GitHub Actions publishes exactly that directory after tests pass on `main`. Deployment receives Pages and OIDC permissions only in its own job; test jobs use read-only repository permissions. No source tree, native report output, credential file or local operational note is part of the uploaded artifact.
