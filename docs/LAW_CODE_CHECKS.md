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

## Draft-rule execution

`GET /api/dosare/rule-drafts/checks?id=...&act=&limita=` runs the same narrow
delegated-norm check against promoted `law-rule-draft-v1` records in one dossier.

The response contract is `law-rule-execution-v1`; rows use
`law-rule-execution-row-v1`. Each row keeps the `rule_draft_id`, `candidate_id`,
provision identity, source hash and matched local delegated-norm checks.

Row states are deliberately bounded:

- `candidate_issue_not_verdict`: the promoted draft rule matched a local
  delegated-norm gap signal.
- `no_local_candidate_signal`: no matching local signal was found for that draft
  rule.

Both states are review inputs. They do not prove legal compliance,
non-compliance, or source completeness.
