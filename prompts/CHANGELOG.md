# Prompt changelog

## v1 - 2026-10-24 (baseline)
- One short line per schema field, no rules for edge cases.
- Purpose: a reference point for comparing the cloud and the local model.

## v1 - 2026-11-02 (schema update)
- Added one line for each new schema field: `escalation_threat`, `repeat_contact`, `deadline`, `tracking_number`.
- No other change: v1 stays the baseline without edge-case rules. Runs before this date used the 8-field schema and are
  not comparable with later runs.
- `product` object replaced by a top-level `order_id` and a `products` list (an order can contain several products); the
  last line of the prompt now describes these two fields.

## v2 - 2026-11-03 (labeling rules)
Written after the v1 run `2026-11-03_01-46-08__v1` (cloud 0.93, local 0.78 / 0.77 mean field accuracy). Each change
targets an error group seen in v1:
- **priority** (worst field: local 0.23, cloud 0.73): the local model answered `high` for 61 of 75 tickets, the cloud
  model missed `urgent`. Added a "start from medium" rule with explicit reasons for each level.
- **category**: definitions for every category plus the root-cause rule; `usage_help` when the customer cannot tell a
  defect from a settings problem (t19, t28); invoices are `payment` (t10); spam and empty messages are `other` (t26, t37).
- **requested_action**: warranty question on a broken product is `repair` (t15, t22); requests outside the list are
  `other` (t11, t13, t20, t40).
- **sentiment**: a calmly described problem is `neutral` (t20, t29, t40); sarcasm is `negative`.
- **language**: when a text is `mixed`; transliterated Ukrainian is `uk`.
- **needs_human**: status and delivery-date questions are `false` (t03, t31, t36); technical diagnosis is `true`.
- **order_id / tracking_number**: normalization to `ES-12345`, ES numbers are never tracking numbers (local t03, t13, t33).
- **products**: category mapping for unlisted types (monitor, smartwatch -> `other`; charging case -> `headphones`),
  empty list instead of an `unknown` entry (t10, t40).
- **Required fields**: the cloud model omitted `needs_human` twice (t49, t75) and invented a product category (t74);
  the prompt now says every field is required and lists the categories with examples.
- Instructions inside the ticket are treated as ticket content (t31).
