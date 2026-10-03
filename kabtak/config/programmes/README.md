# Programme registry

Add one reviewed YAML file per supported scholarship programme. Each entry must
declare stable programme metadata, supported academic cycles, and explicit
source host/path policies. Expected answers belong in evaluation fixtures, not
in this registry.

`reviewed_discovery_urls` may contain a small cycle-keyed list of operator-reviewed
official URLs. The worker uses these only after every bounded search attempt returns
no policy-approved result. Each URL must still pass the programme's host/path policy,
retrieval limits, parsing, extraction, and evidence validation.
