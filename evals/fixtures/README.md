# Shared eval fixtures

## smc_ground_truth_server.py

Loopback ground-truth fixture for SMC browser qualifications (FC2-B contract
families: `click | fill | select | scroll`, `navigate`, typed `wait`).

- stdlib only, `127.0.0.1`, ephemeral port, context manager
- never import from production code
- one server, many routes; ground truth is data via `/manifest`

### When to use vs per-eval copies

The per-eval `fixture_server.py` copies under `evals/browser_smc_*` back
frozen protocol identities and must stay untouched. Use this shared fixture
for new qualifications that need richer ground truth (name pollution,
ambiguity halt, scroll, navigate, parametrized delays, `hx-*` attributes).

### Routes

| route | purpose |
| --- | --- |
| `/unique/click` | unique `kind=button name="Run check"`; click reports one event |
| `/unique/fill` | canonical FC2-C `kind=input name="Project code"` + Save code |
| `/unique/select` | native `<select name="Region">` (east/west) |
| `/unique/scroll` | `role=region` scroll container, 40 items, debounced scroll events |
| `/pollution/button-text-child` | FC2-B phenomenon: button + same-name StaticText child; kind+name resolves, name-only is polluted |
| `/ambiguous/two-buttons` | two `kind=button name="Deploy"`; contract must halt, `/state` stays empty |
| `/wait/delayed-enable?delay_ms=N` | typed wait `property=enabled` then single mutation; `early_click` events are failures |
| `/wait/delayed-appear?delay_ms=N` | wait `visible` on an object absent at load |
| `/navigate/page-a` `/navigate/page-b` | distinct page resources for the navigate clause |
| `/htmx/click` | `hx-post/hx-target/hx-swap` attributes in DOM (observation hook); local fetch shim, no CDN |

### Ground truth surfaces

- `GET /manifest` — expected canonical objects per route (`kind`, `name`,
  `expected_id`, `kind_name_matches`, `name_only_matches`)
- `GET /state` — append-only server-side event log; assert the mutation hit
  the expected node exactly once
- `POST /event` — endpoint the pages report to

### Verify

```sh
python3 evals/fixtures/smc_ground_truth_server.py   # HTTP-level self-check (12 routes)
python3 evals/fixtures/browser_smoke.py             # browser-level smoke (11 checks, playwright)
```

`browser_smoke.py` takes element names from `/manifest` (no hardcoded DOM
expectations) and asserts effects against the `/state` event log. The
pollution check counts the CDP full AX tree (`Accessibility.getFullAXTree`),
because `aria_snapshot()` folds the button text into the button name and
would report a false count of 1.

Verified 2026-09-18 (local): HTTP self-check 12 routes PASS; browser smoke
11/11 PASS (click/fill/select/scroll events, pollution raw AX occurrences
>= 2, ambiguous kind+name == 2 with zero side effect, delayed enable with no
early_click, delayed appear, navigate a→b, hx shim).
