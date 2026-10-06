# Pre-formal amendment: preserve provider registry in isolated DATA_DIR

Time: 2026-10-06, formal rows still 0/84.

The experiment intentionally gives every attempt a fresh DATA_DIR. ProviderRegistry loads its
full local registry from `DATA_DIR/providers.local.json` / `DATA_DIR/providers.json`; an empty
fresh DATA_DIR therefore degrades to the legacy single-provider synthesis even when LLM_MODEL
is fully qualified. Preflight v4 mechanically exposed this: Weak was still sent through the
DeepSeek endpoint.

Before engine construction, the worker now byte-copies the canonical runtime provider registry
snapshots into each fresh attempt DATA_DIR and records their SHA256 values. This does not alter
the canonical files, physical model identities, cases, arm treatment, order, thresholds, or
production configuration. It restores the provider-routing input that isolation otherwise
removed. All four model×arm preflights must pass in fresh v5 namespaces before formal row 1.
