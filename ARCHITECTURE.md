# Architecture

Educational local RAG for blood-test literacy. **Not a medical device, not HIPAA-certified.** Controls below are alignment patterns (minimum necessary, de-identification, audit, human oversight), not a BAA or production security program.

## Runtime (default)

Everything that matters stays on the workstation. Ollama serves `llama3.2` (chat) and `nomic-embed-text` (embeddings). The Streamlit UI never writes a patient lab PDF into the knowledge index.

```text
                    ┌─────────────────────────────────────────────┐
                    │                 Workstation                 │
  lab PDF ──parse──►│  agents/lab_parser  (ephemeral session)     │
                    │  markers scoped by question                 │
                    │                                             │
  NIH/PMC ──ingest─►│  knowledge/documents  → FAISS (chroma_db/)  │
                    │  PHI-redacted before embed                  │
                    │                                             │
  question ──► guardrails ──► retrieve k=4 ──► llama3.2 ──► UI    │
                    │         audit.jsonl (hashed, redacted)      │
                    └─────────────────────────────────────────────┘
                                      │
                                      ▼  (optional flags only)
                         Comprehend Medical / Bedrock ApplyGuardrail
```

| Path | Role |
| --- | --- |
| `app.py` | Streamlit: index corpus, parse labs, chat |
| `agents/` | Lab parse, marker bands, coordinator |
| `rag/` | Load, FAISS, SafeOllamaEmbeddings, QA chain |
| `security/` | PHI regex, guardrails, audit, optional AWS adapters |
| `knowledge/` | `sources.yaml` catalog + public extracts |
| `evals/` | Scope / guardrail / retrieval / live scoring |
| `.github/workflows/tests.yml` | pytest on push (no Ollama) |

The on-disk index directory is named `chroma_db/` for history; the store is **FAISS**. Chroma’s Windows `/tokenize` sidecar was dropped for that reason.

## Data flow

1. **Knowledge ingest** (`python -m knowledge.ingest`) fetches public pages into `knowledge/documents/`. Patient filenames (`lab-results-*`) are blocked from extra-file indexing.
2. **Index** redacts identifier patterns, chunks (~700/100 overlap), embeds in small batches, writes FAISS locally.
3. **Lab parse** reads a PDF in memory, extracts Quest-style testosterone fractions and other markers, then deletes the temp file. Session state holds numbers only.
4. **Chat** runs `check_input` (injection, identifier requests, denied topics). If no marker matches the question, RAG is skipped so the model cannot invent an unrelated analyte (for example DHEAS) from retrieved chunks.
5. **Retrieve-and-generate** uses only structured findings **in scope** plus top-4 chunks. Output is PHI-redacted again. Audit log stores a hash and a redacted preview, not raw SSN/name.

### What leaves the box

| Data | Local default | If AWS flags are on |
| --- | --- | --- |
| Lab PDF | Stays on disk briefly under `data/uploads/`, then deleted; not indexed | Still should not leave VPC without a BAA |
| Marker values | In Streamlit session + prompt to local Ollama | Same, unless you point the LLM at a cloud API (this repo does not) |
| Identifiers | Redacted before embed, log, and answer | Comprehend Medical `DetectPHI` if `PHI_BACKEND=comprehend_medical` |
| Questions | Hashed in `logs/audit.jsonl` | Bedrock `ApplyGuardrail` if enabled |

Demographics used for range selection are **bands only** in the prompt and logs (age band, sex-specific ranges on/off, weight considered yes/no). Exact age, weight, and sex are not echoed.

## Trust boundaries

- **Knowledge vs labs.** Scientific corpus is the only vector-store tenant. Labs are session memory.
- **UI vs model.** Guardrails run before retrieval. Identifier questions (`what is my SSN`) never hit FAISS.
- **Eval vs production LLM.** Unit tests and GitHub Actions score deterministic scope/PHI/guardrails. `--retrieve` / `--live` evals need a local index and Ollama and are not CI.

## Threat model (portfolio)

| Threat | Control | Residual risk |
| --- | --- | --- |
| Prompt injection | Regex input filter | Novel jailbreaks; local LLM still sees retrieved text |
| Identifier leak | Redact + refuse SSN/name/address asks | Regex is not Comprehend Medical; OCR/PDF layout can miss values |
| Wrong marker (Quest FREE vs TOTAL) | Row-specific testosterone rules; scoped prompt | Unusual lab formats still parse wrong |
| Over-retrieval (cystatin vs statin) | Word-boundary focus groups; question-scoped findings | Several topics in one question union groups |
| Hallucinated ranges or drugs | Grounding instruction; refuse if not in context; live eval for invented therapies | llama3.2 can still ignore the prompt |
| Indexing a lab PDF | Filename block; warning if a lab-like file was indexed | User can rename a lab to look like a paper |
| Audit leakage | Hash + redact preview | Log file is local and gitignored, not KMS-encrypted |

## Production analogue (AWS)

This mapping is for interview discussion. Enabling boto3 backends without a BAA, private subnets, and KMS does **not** make the app HIPAA-eligible.

| Concern | This repo | AWS |
| --- | --- | --- |
| PHI detection | `security/phi.py` | Comprehend Medical `DetectPHI` |
| Prompt/completion policy | `security/guardrails.py` | Bedrock Guardrails `ApplyGuardrail` |
| Grounding | Retrieve-only prompt + evals | Contextual grounding checks |
| Audit | `security/audit.py` | CloudTrail + restricted buckets |
| Pre-index scan | Redact on ingest | Macie / Comprehend |
| Encryption / network | Local disk, gitignored uploads | KMS CMKs, IAM, private VPC |

Flags: `PHI_BACKEND=comprehend_medical`, `BEDROCK_APPLY_GUARDRAIL=true`. See `.env.example`.
