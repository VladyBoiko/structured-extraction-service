# Judge calibration: judge prompt v2

10 answers labelled by a person ([evals/judge_calibration.yaml](../../judge_calibration.yaml)) and by the judge (claude-haiku-5-5, effort medium).

The judge graded every answer 3 times; agreement and kappa use its majority label.

- agreement: **0.80** (per repeat: 0.90, 0.80, 0.80)
- Cohen's kappa: **0.68**
- stability: the same label in all 3 repeats for **0.90** of the answers
- human labels: {'correct': 5, 'incorrect': 3, 'partial': 2}; judge labels: {'correct': 5, 'incorrect': 3, 'partial': 2}
- cost: $0.005

For comparison, the deterministic scorers on the same answers (pass counted as correct) agree with the person on **0.80** (10 answers); they disagree on t18, t38: a correct answer that mentions an outdated value fails the trap check, and a confusing or false "not in the documents" note passes, since every key fact is there.

Confusion (rows: person, columns: judge):

| person \ judge | correct | partial | incorrect |
|---|---|---|---|
| correct | 4 | 1 | 0 |
| partial | 1 | 1 | 0 |
| incorrect | 0 | 0 | 3 |

| id | person | judge (majority) | judge, every repeat | person's note | judge's reason |
|---|---|---|---|---|---|
| t36 | correct | correct | correct / correct / correct |  | The assistant gives the 24-month TV warranty and the 14-day repair time, both matching the reference answer. It omits the replacement-device option for longer repairs, but that is extra context not needed to answer the question directly. |
| t17 | incorrect | incorrect | incorrect / incorrect / incorrect |  | The reference answer states that ElectroStore has no physical stores and is online-only with delivery via Nova Poshta and Ukrposhta. The assistant answered 'I don't know, the documents have no answer', which fails to give the customer the actual fact that no physical stores exist. Since the reference has an answer, 'I don't know' is incorrect. |
| t11 | correct | correct | correct / correct / correct |  | The assistant answers 'Nein' and states that in-ear headphones with a removed hygiene seal are excluded from return, matching the reference answer. The first claim cites a product page, but source labels are checked separately and the content is consistent with the reference. |
| t39 | incorrect | incorrect | incorrect / incorrect / incorrect | answers from the law on faulty goods, not the store's rules for damage in transit; none of the expected steps; false 'not in the documents' | The reference answer gives the store's procedure: report within 48 hours of delivery with order number, photos, description, keep packaging, and the store replaces or refunds at customer's choice. The assistant instead cites general consumer law about quality defects (14 days, weight-based delivery costs), does not mention the 48-hour reporting window or the store's replace-or-refund options, and explicitly says the store's procedure is not in the documents, which contradicts the reference answer. The core practical guidance is missing and the content is misleading. |
| t29 | correct | correct | correct / correct / correct |  | The reference answer is "I don't know" because the documents contain no laptop assortment information. The assistant also says it doesn't know, that the store documents have no answer to this question. This matches the reference in substance, so it is correct. |
| t18 ⚠️ | partial | correct | correct / correct / correct | phone hours for Germany and Austria are right, but a Ukrainian customer is not told about the chat and email that are their way to contact support | The assistant correctly states the phone hotline is available for Germany and Austria on weekdays 9:00–18:00 (CET), matching the core of the reference answer. It omits the Ukraine chat and email alternatives, but the question asks only when the phone line is available, so the answer is fully responsive. |
| t34 | incorrect | incorrect | incorrect / incorrect / incorrect | suggests an opened or missing box does not matter, from a law article on off-premises contracts; the store policy requires the original packaging; false 'not in the documents' | The reference says a non-defective item is taken back only with its original packaging, so without the box returns may be refused. The assistant instead cites the special right to rescind off-premises contracts, which does not address the general case, and its note that store rules on returns without the box are 'not in the documents' contradicts the reference. The core answer is missing and the customer is likely misled. |
| t14 ⚠️ | correct | partial | correct / partial / partial |  | The core answer is right: the customer pays import VAT and customs fees, and shipments to Switzerland are sent uncleared. However, the claim that these are paid 'bei der Zustellung an den Paketdienst' is an unsupported and confusing detail that the reference does not contain and that misstates when and to whom payment is made. |
| t38 | partial | partial | partial / partial / partial | borderline: every price given is right and the list by country shows that the price depends on the destination, but Poland, Czechia and Slovakia (9.90 EUR, free from 150 EUR) are missing, so a customer there gets no price although the documents have it; the answer also never says plainly that the price depends on the country | The answer correctly gives the prices for Germany, Austria, Switzerland and Ukraine (Nova Poshta), matching the reference. It omits the Poland, Czechia and Slovakia rate (9.90 EUR, free from 150 EUR), which the reference includes, and adds a Ukrposhta 55 UAH figure the reference does not mention. The core is right but incomplete. |
| t35 | correct | correct | correct / correct / correct |  | The assistant answers 'Nein' and explains that in-ear headphones with removed hygiene seal cannot be returned, matching the reference answer. The second sentence restates the same rule with a different source, which is consistent and not confusing. |
