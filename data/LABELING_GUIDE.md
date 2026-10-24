# Golden set labeling rules

Rules for the reference labels in `golden/<id>.json`; they keep the labeling consistent.
The baseline prompt (v1) does not contain these rules, so some disagreements with the models are expected.

**category** - what the problem is about. What the customer wants done goes to `requested_action`, so the two fields
never describe the same thing (a double charge is `payment` + `refund`, a broken product is `product_defect` + `repair`).
- `order_status` - an order that has not shipped yet: processing, confirmation
- `order_change` - cancel, modify or return an order when nothing is wrong with the product
- `delivery` - tracking, delay, lost parcel, parcel damaged in transit, delivery terms
- `payment` - charges, double charges, failed payments, invoices
- `product_defect` - the product is broken, damaged or does not work (including on arrival and under warranty)
- `usage_help` - the product works, but the customer needs help to set it up or use it
- `product_question` - before or regardless of a purchase: specs, compatibility, availability
- `account` - login, profile, loyalty program
- `other` - thanks, spam, anything else

If several categories fit, choose the root cause: the thing that has to be fixed first.

**priority**:
- `urgent` - threat of a complaint or legal action, risk of damage (water, smoke), or a customer deadline within ~24 hours
- `high` - the customer lost money (double charge), strong anger
- `medium` - a regular problem
- `low` - general questions, thanks, spam

**sentiment**: `negative` - complaint, defect or clear dissatisfaction; `neutral` - polite question; `positive` - thanks or praise.

**language**: `en` / `uk` / `de` when the text is mostly in one language (brand names and single borrowed words do not count);
`mixed` when two or more languages are used in whole phrases.

**requested_action**: what the customer asks for (`information` - only an answer to a question; `none` - asks for nothing).
- A broken product plus a question about the warranty is `repair`: the customer wants it fixed under warranty.
- A clear request that is not in the list (unlock an account, find a lost parcel) is `other`.

**needs_human**: `true` if an agent has to investigate or change something in an order, payment or warranty case; `false` for a
simple question, thanks, spam, or a status that can be looked up automatically.

**product.name** - the product name or model as the customer wrote it; `null` for generic words such as "tv" or "phone".

**product.category** - the product type; `unknown` if it cannot be determined.

**product.order_id** - in the form `ES-12345`; `null` if there is no order number.

**summary** - one short English sentence (up to 200 characters): what happened and what the customer wants, with the product
and order number when present. Used as a reference for manual comparison; not scored.
