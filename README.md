# Bloodwork Project

Educational RAG assistant for **blood-test literacy**. It retrieves from NIH/PMC-style white papers you provide, parses a lab PDF in memory, and discusses markers, literature ranges, and follow-up themes.

It is **not** a medical device, **not** a diagnosis engine, and **not** HIPAA-certified. The controls below are the kind a small company would put in place to *align* with HIPAA and AWS Responsible AI. A covered entity still needs a BAA, policies, and a security program.

## Demo

**[Loom walkthrough of the Bloodwork Project](https://www.loom.com/share/3ee0296261524997acd4a0151ce18b53)**

Index the curated corpus, parse a lab PDF in memory, then ask scoped questions with sources.

## What this repo keeps (from the prior RAG app)

- PDF load → chunk → FAISS → Ollama retrieve-and-generate
- Prompt-injection input filters
- Output sanitization
- Append-only audit log

Removed: tutorial `learning/` scripts, sample PDFs, and extra chat demos.

## Privacy model

Patient identifiers (name, SSN, address, payment, visit time/location, and similar) are **redacted** before embedding, logging, or answering.

Sex, age, and weight may be used **ephemerally** so the model can pick sex- and age-banded reference intervals. Logs and chat show only:

- whether sex-specific ranges were used
- an age **band** (ages ≥90 collapse to `90+`)
- whether weight was considered — not the raw value

Lab PDFs are parsed in memory and **not** written into the vector store. Only scientific knowledge PDFs are indexed.

## AWS mapping (AI Practitioner)

Local default: Ollama on the workstation so lab files need not leave the box.

Optional production path (HIPAA-eligible services + BAA):

| Concern | Implementation in this repo | AWS analogue |
| --- | --- | --- |
| PHI detection | `security/phi.py` | Amazon Comprehend Medical `DetectPHI` |
| Policy on prompts/completions | `security/guardrails.py`, denied topics | Amazon Bedrock Guardrails + `ApplyGuardrail` |
| Grounding / hallucination | retrieve-only prompt, refuse if missing | Bedrock contextual grounding checks |
| Audit | hashed, redacted JSONL | CloudTrail + restricted log buckets |
| Knowledge hygiene | redact before FAISS ingest | Macie / Comprehend scan pre-KB |
| Encryption & access | gitignored uploads, local-first | KMS, IAM least privilege, private VPC |

Set `PHI_BACKEND=comprehend_medical` and/or `BEDROCK_APPLY_GUARDRAIL=true` when credentials and a BAA exist. See `.env.example`.

## Setup

Python 3.11 or 3.12 and [Ollama](https://ollama.com/download):

```powershell
ollama pull llama3.2
ollama pull nomic-embed-text
```

```powershell
cd C:\Users\PC\Projects\Bloodwork-Project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

## Use

1. Click **Index curated corpus** (Ollama must be running with `nomic-embed-text`). First index can take several minutes.
2. Optionally upload a lab PDF and **Parse labs**. Identifiers are stripped; markers stay in session memory.
3. Ask what the papers say about those markers, ranges, and lifestyle discussion points.
4. Expand **Sources**. If the corpus does not support a claim, the model is instructed to say it does not know.

If indexing fails with a `/tokenize` connection error, that was Chroma’s Windows sidecar — this project now uses FAISS. Install `faiss-cpu`, restart Streamlit, and retry. You do not need to change browsers.

An eval harness scores scope (right markers), guardrails, retrieval, and whether named therapies appear only if they were retrieved. See **Eval**.

## Layout

```text
Bloodwork-Project/
├── app.py
├── agents/           # lab parse + interpret coordinator
├── rag/              # load, index, chain
├── security/         # guardrails, PHI, audit, AWS adapters
├── knowledge/        # source catalog + documents/
├── evals/            # YAML cases + scoring harness
├── tests/
├── .github/workflows/
└── config/
```

## Tests

GitHub Actions runs the same command on every push to `main` and on pull requests. Unit tests do not need Ollama.

```powershell
python -m pip install pytest pyyaml
python -m pytest
```

## Eval

Cases live in `evals/cases.yaml` (synthetic Quest-style panel, no real PHI). Offline checks do not need Ollama.

```powershell
python -m evals.runner
python -m evals.runner --retrieve
python -m evals.runner --live
```

`--retrieve` / `--live` need a local FAISS index (`Index curated corpus`) and Ollama. Retrieval checks that metformin, berberine, statin/ApoB, and similar terms actually come back from the corpus. Live checks that a testosterone question does not recite LDL, that zinc ranges are refused if missing, and that named therapies are not invented outside retrieved context.

## Knowledge corpus

Catalog (URL + what each page should teach) is `knowledge/sources.yaml`.

```powershell
python -m pip install -r requirements.txt
python -m knowledge.ingest
```

That writes public-page extracts to `knowledge/documents/`. Paywalled items (AccessMedicine, some Clin Chem, ASHP book) are skipped or stored as stubs — use the NIH/PMC stand-ins instead. Then in the app click **Index curated corpus**.

MedlinePlus/NHLBI encyclopedia pages for TSH, free T4, vitamin D, ferritin/iron, hs-CRP, insulin, UA, ApoB, Lp(a), cystatin C, and eGFR are included so those markers have dedicated teaching text.
