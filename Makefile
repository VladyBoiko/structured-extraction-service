PYTHON ?= python

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) main.py

report:
	$(PYTHON) main.py --report-only

test:
	$(PYTHON) -m pytest -q

errors:
	$(PYTHON) -m src.errors

smoke:
	$(PYTHON) main.py --config config.smoke.yaml

# ---- Block 2: RAG (independent of block 1: none of these run the extraction service)
rag-data:          ## build store documents, download external ones, ingest -> data/rag/chunks.jsonl
	$(PYTHON) -m src.rag data

rag-ingest:        ## re-ingest only (incremental: unchanged files come from the cache)
	$(PYTHON) -m src.rag ingest

rag-index:         ## embed chunks and build the Qdrant collections
	$(PYTHON) -m src.rag index

rag-eval-retrieval:  ## recall@5 / MRR on evals/retrieval_questions.yaml
	$(PYTHON) -m src.rag eval-retrieval

rag-ask:           ## answer a question with sources: make rag-ask Q="Скільки днів на повернення?"
	$(PYTHON) -m src.rag ask "$(Q)"

rag-eval:          ## answer the test set 3 times and score the answers (calls Claude)
	$(PYTHON) -m src.rag eval

rag-ci:            ## what the CI runs: retrieval and one answer run, then the quality gates (~$0.03)
	$(PYTHON) -m src.rag eval-retrieval-quick --tag ci
	$(PYTHON) -m src.rag eval --runs 1 --tag ci
	$(PYTHON) -m src.rag ci-check --answers ci --retrieval ci

rag-full:          ## full answer evaluation of the final configuration: 3 runs, judge, faithfulness, gates (~$0.10)
	$(PYTHON) -m src.rag eval --prompt v2 --tag full
	$(PYTHON) -m src.rag judge --tag full --latest
	$(PYTHON) -m src.rag faithfulness --tag full --latest
	$(PYTHON) -m src.rag ci-check --answers full --retrieval run

# Block 2 in one command: corpus -> chunks -> index -> retrieval evaluation -> answers, judge, faithfulness -> gates.
# Every step writes new results next to the earlier ones (full, full_2 ...; run, run_2 ...).
rag:
	$(PYTHON) -m src.rag data
	$(PYTHON) -m src.rag index
	$(PYTHON) -m src.rag eval-retrieval --tag run
	$(MAKE) rag-full

.PHONY: install run report test errors smoke rag rag-full rag-data rag-ingest rag-index rag-eval-retrieval rag-ask rag-eval rag-ci
