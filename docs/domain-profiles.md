# Domain Profiles

The agent uses one LangGraph workflow for three content domains:

| Domain | Typical subdomains |
| --- | --- |
| `beauty` | skincare, haircare, bodycare, makeup basics |
| `wellness` | sleep, stress management, routine, recovery |
| `healthy_lifestyle` | nutrition, exercise, hydration, sedentary habits |

## Run The CLI

Pass `--domain` when the domain is known. Otherwise, the router infers the
domain and subdomain from `--focus_keyword`.

```bash
python main.py --domain beauty --focus_keyword "夏季防晒"
python main.py --focus_keyword "睡前作息"
python main.py --domain healthy_lifestyle --focus_keyword "久坐办公"
```

An explicit domain takes precedence over keyword inference. An unsupported
explicit domain is rejected before memory retrieval. Low-confidence inference
pauses the graph and asks the user to confirm both domain and subdomain.

Profiles are versioned in `src/domain/profiles.py`. They own subdomain
taxonomies, prohibited topics and claims, disclaimers, hashtag seeds, visual
guidelines, and evidence-source allowlists.

## Evidence

Set the Tavily key before running factual wellness or healthy-lifestyle topics:

```bash
export TAVILY_API_KEY="..."
```

The default allowlist is:

```text
who.int
nih.gov
cdc.gov
nhs.uk
nhc.gov.cn
chinacdc.cn
```

Evidence retrieval runs for medium-risk or `basic_science` topics when the
profile requires it. A required evidence search that fails or returns no
allowlisted source stops the workflow before outline generation. Search
snippets are marked unverified and do not become verified medical claims.

## Review And Persistence

Every publish review includes the editable package, domain metadata, risk
flags, matched policy rules, final-policy issues, and serialized evidence
items.

Only an explicitly approved package that passes the final deterministic policy
guard can reach persistence. Human edits to visible text return through R2
compliance and then require another review. Rejection, missing required fields,
unsupported claims, treatment language, medication advice, dosage advice, or
guaranteed outcomes cannot call either structured or vector memory writes.

Published records and retrieval are partitioned by domain and subdomain.
Performance analytics are available through
`XHSMemoryManager.get_performance_by_domain()`.

## Legacy Migration

`XHSMemoryManager.init_db()` runs the idempotent structured-memory migration.
Existing rows without domain metadata are backfilled as:

```text
domain=beauty
subdomain=skincare
profile_version=legacy-v1
risk_level=low
```

The first memory retrieval also backfills vector metadata and records a
`vector_domain_backfill_v1` event after successful completion. Empty databases
are not marked as migrated, so later legacy imports can still be backfilled.

Old LangGraph checkpoints without `domain_context` are hydrated at resume with
the beauty/skincare compatibility profile and emit a warning.
