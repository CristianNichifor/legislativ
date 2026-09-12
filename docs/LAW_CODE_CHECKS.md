# Deterministic law-as-code checks

The first executable check is deliberately narrow:

`GET /api/law-code/delegated-norms?act=&limita=`

It reads the local unmet-obligations report and returns candidate gaps where a
law appears to delegate an implementing act, but the local graph cannot show a
matching implementing act.

## Contract

Response contract: `law-code-delegated-norms-v1`

Each row uses `law-code-check-delegated-norm-v1` and includes:

- `status`: `candidate_gap_not_verdict`
- `check`: `delegated_norm_not_found`
- `act_id`
- `locator`
- `provision_id`, when both act and locator are known
- expected `instrument`
- `deadline`
- `days_overdue`
- evidential `severity`
- quoted source text and searched relation
- nearby candidates found in the graph
- provision actions
- row-level limitations

## Boundaries

This endpoint does not fetch official sources, does not run AI and does not
decide legal truth. A missing implementing act can mean:

- the implementing norm was not issued;
- the local corpus has not collected that source family completely;
- the graph did not extract the relationship.

The output is suitable for review queues, matrix drilldowns and dossier notes,
not for automatic legal conclusions.
