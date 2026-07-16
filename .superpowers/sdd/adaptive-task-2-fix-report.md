# Task 2 Review Fix Report

## Finding fixed

The real `angle_strategist_node` accepted an `AngleStrategy` whose three angles
all used the same `narrative_form`. The current authoritative content policy
does not encode an exception that can prove only one form is safe, so every
three-angle strategy now deterministically requires at least two distinct
narrative forms.

## RED evidence

Added a real-node regression test that replaces only the model boundary and
returns a fully schema-valid response containing three `scenario_story`
narrative plans.

```text
$ pytest -q tests/nodes/test_domain_nodes.py::test_angle_strategist_rejects_one_repeated_narrative_form
F
E Failed: DID NOT RAISE ValueError
1 failed in 4.62s
```

## GREEN implementation and evidence

After `AngleStrategy` parsing succeeds, the node collects the three
`narrative_form` values for each strategy and raises a clear `ValueError` when
fewer than two distinct forms are present. No policy exception, compatibility
default, or schema weakening was added.

```text
$ pytest -q tests/nodes/test_domain_nodes.py::test_angle_strategist_rejects_one_repeated_narrative_form
.
1 passed in 3.35s

$ pytest -q tests/nodes/test_domain_nodes.py -k 'angle_strategist and narrative'
..
2 passed, 30 deselected in 3.33s

$ pytest -q tests/prompts/test_composer.py tests/nodes/test_domain_nodes.py tests/nodes/test_metadata_flow.py -k 'not test_human_focus_keyword_edit_invalidates_downstream_artifacts_and_reruns_r2'
103 passed, 1 deselected, 2 warnings in 3.53s

$ python -m compileall -q src main.py
# exit 0

$ git diff --check
# exit 0
```

The positive real-node test proves that two forms across three angles are
accepted when one of those forms is repeated.

## Self-review

- Production scope is limited to deterministic post-parse validation in
  `src/nodes/node_b_angle_strategist.py`.
- Tests invoke the real node and mock only `get_model`.
- Emoji behavior remains permitted and optional.
- Task 1 strict schemas and compatibility behavior are unchanged.
- No Task 3+ visual, storyboard, renderer, asset, persistence, or publish code
  was touched.
