# Retrieval results

16 questions, recall@5 and MRR@10. Gold = evidence quote in the retrieved chunk. Per question gold and top-5: [per_question.md](per_question.md).

## Embedding models (vector search, structure-aware chunks)

| model | hit@1 | recall@5 | MRR@10 | ms/query | misses@5 |
|---|---|---|---|---|---|
| e5-large | 0.62 | 0.94 | 0.71 | 18 | r16 |

## Search modes x chunking (embeddings: e5-large, reranker: bge-m3)

| chunks | mode | hit@1 | recall@5 | MRR@10 | ms/query | misses@5 |
|---|---|---|---|---|---|---|
| structured | vector | 0.62 | 0.94 | 0.71 | 12 | r16 |
| structured | bm25 | 0.25 | 0.75 | 0.48 | 2 | r02 r04 r10 r16 |
| structured | hybrid | 0.50 | 0.88 | 0.64 | 15 | r04 r16 |
| structured | rerank | 0.81 | 0.94 | 0.88 | 4518 | r16 |
| fixed | vector | 0.69 | 0.88 | 0.74 | 10 | r10 r16 |
| fixed | bm25 | 0.44 | 0.81 | 0.57 | 2 | r04 r10 r16 |
| fixed | hybrid | 0.56 | 0.81 | 0.66 | 11 | r04 r10 r16 |
| fixed | rerank | 0.75 | 0.94 | 0.84 | 3770 | r16 |

## Structure-aware chunk size sweep

| max tokens | merge siblings below | chunks | avg tokens | mode | hit@1 | recall@5 | MRR@10 | misses@5 |
|---|---|---|---|---|---|---|---|---|
| 300 | 40 | 1257 | 189 | vector | 0.62 | 0.88 | 0.73 | r04 r16 |
| 300 | 40 | 1257 | 189 | hybrid | 0.62 | 0.88 | 0.75 | r04 r16 |
| 300 | 40 | 1257 | 189 | rerank | 0.56 | 0.88 | 0.72 | r04 r16 |
| 300 | 150 | 1043 | 228 | vector | 0.56 | 0.88 | 0.71 | r04 r16 |
| 300 | 150 | 1043 | 228 | hybrid | 0.50 | 0.88 | 0.68 | r04 r16 |
| 300 | 150 | 1043 | 228 | rerank | 0.69 | 0.94 | 0.81 | r16 |
| 380 | 150 | 834 | 282 | vector | 0.62 | 0.94 | 0.71 | r16 |
| 380 | 150 | 834 | 282 | hybrid | 0.56 | 0.88 | 0.68 | r04 r16 |
| 380 | 150 | 834 | 282 | rerank | 0.75 | 0.94 | 0.84 | r16 |

## Version traps: the status filter (hybrid + rerank)

| filter | recall@5 | outdated chunks in top-5 | questions affected |
|---|---|---|---|
| status=current (default) | 1.00 | 0 | - |
| no filter | 1.00 | 2 | r01 r05 |

## Rank of the first relevant chunk per question

| question | structured/vector | structured/bm25 | structured/hybrid | structured/rerank | fixed/vector | fixed/bm25 | fixed/hybrid | fixed/rerank |
|---|---|---|---|---|---|---|---|---|
| r01 Скільки днів у мене є, щоб повернути товар, замовлений з дос | 3 | 1 | 2 | 1 | 1 | 1 | 1 | 1 |
| r02 Was kostet die Rücksendung, wenn ich in Österreich wohne? | 4 | 6 | 4 | 1 | 3 | 3 | 3 | 2 |
| r03 How much do I pay with Care+ if I drop my phone and crack th | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 |
| r04 Чому моя знижка Gold не застосувалась до товару, який уже бу | 5 | – | – | 1 | 5 | – | – | 1 |
| r05 Від якої суми доставка у відділення Нової Пошти безкоштовна? | 4 | 2 | 3 | 2 | 5 | 1 | 3 | 2 |
| r06 Ist der Sony WF-1000XM5 wasserdicht? | 1 | 2 | 2 | 2 | 1 | 2 | 2 | 2 |
| r07 Скільки годин працює JBL Tune 770NC з увімкненим шумозаглуше | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 |
| r08 My WF-1000XM5 earbuds won't turn on, how do I reset them? | 1 | 5 | 1 | 1 | 1 | 1 | 1 | 1 |
| r09 У який строк продавець має усунути недоліки товару згідно із | 1 | 2 | 2 | 1 | 1 | 5 | 3 | 1 |
| r10 How many days does a consumer have to withdraw from an onlin | 3 | 9 | 5 | 1 | 9 | – | 8 | 1 |
| r11 Kann ich In-Ear-Kopfhörer zurückgeben, wenn ich die Versiege | 1 | 5 | 1 | 1 | 1 | 3 | 1 | 1 |
| r12 Можна оплатити частинами order на 1000 грн? | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 |
| r13 Do you deliver to London? | 1 | 2 | 1 | 1 | 1 | 4 | 1 | 1 |
| r14 Wer zahlt den Zoll bei einer Lieferung in die Schweiz? | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| r15 Посилку вже відправили, чи можна ще змінити адресу доставки? | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| r16 I paid for my order in Ukraine in instalments and returned t | – | – | – | – | – | – | – | – |
