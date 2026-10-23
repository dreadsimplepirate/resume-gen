---
name: resume-gen
description: |
  Builds a YAML work-experience library from sample resumes and generates ATS-ready,
  humanized resumes tailored to a job description (.docx + .pdf), injecting a configurable
  number of JD keyword bullets (default 3) into existing roles. Use when asked to tailor a
  resume or CV to a job posting, build or update a resume profile from existing resumes,
  extract job-description keywords for ATS matching, or produce resume documents.
---

# Resume Generator (`resume_gen.py`)

Single-file Python CLI. `ingest` builds `profile.yaml` from real resumes; `tailor` rewrites it against a job description and exports `.docx` + `.pdf`.

## Requirements

Python 3.9+ and `PyYAML`. PDF input also needs `pypdf` or system `pdftotext`.

Set credentials in `.env` (loaded from the current directory, then the script directory; existing environment variables take precedence):

```dotenv
OPENCODE_API_KEY="your-api-key"
OPENCODE_BASE_URL="opencode-go"
OPENCODE_MODEL="your-model"
```

Keys are also read from `OPENAI_*` and `OPENROUTER_*` variables. `--api-key`, `--base-url`, and `--model` override env for one run. Base URL accepts `opencode-go`, `opencode`, `openrouter`, or any OpenAI-compatible URL; the model ID is routed to the matching API family (Chat Completions, Responses, Anthropic Messages, Gemini) automatically.

## Workflow

```
- [ ] 1. Ingest sample resumes into profile.yaml
- [ ] 2. Curate profile.yaml (optional)
- [ ] 3. Tailor to the job description
- [ ] 4. Review the output and report
```

### 1. Ingest

```bash
python3 resume_gen.py ingest resume1.pdf resume2.docx -o profile.yaml
```

Accepts `.pdf`, `.docx`, `.txt`, `.md`, `.yaml`, `.yml`. Re-running merges into an existing profile: new roles, bullets, skills, education, and certifications are added; duplicate bullets are dropped; existing `basics` and `voice_profile` values win, so manual edits survive.

### 2. Curate `profile.yaml` (optional)

- `basics`, `skills`, `certifications`, `education`, `roles[].bullets` — plain text, edit directly.
- `voice_profile.sample_bullets` — verbatim bullets that anchor the humanizer's sentence length and verb style.
- `voice_profile.uses_dashes` — allow em/en dashes; set automatically from the samples at ingest time.

### 3. Tailor

```bash
python3 resume_gen.py tailor \
  -p profile.yaml \
  -j jd.txt \
  -o output/ \
  --name-prefix acme_security \
  --custom-bullets 3
```

`-j` accepts the same file formats as `ingest`. `-p` must already exist — `tailor` never creates the profile.

### 4. Review

Read `output/<name-prefix>_report.json`:

- `extracted_keywords` — JD keywords the resume now targets.
- `custom_bullets_report` — every injected bullet with its company, title, and matched keywords.
- `skills` — filtered after the LLM pass: only skills from `profile.yaml` or exact extracted keywords survive, so invented tools are dropped.

If the model returns a different number of custom bullets than `--custom-bullets` asked for, the command prints a warning with both numbers.

Custom bullets are model-drafted claims about the candidate's experience, not facts taken from the sample resumes. Confirm each one is true before the user sends the resume.

## Outputs

| File | Contents |
| --- | --- |
| `output/<name-prefix>.docx` | Single-column Word document |
| `output/<name-prefix>.pdf` | PDF 1.4, centered navy header, right-aligned dates, hanging-indent bullets |
| `output/<name-prefix>_report.json` | Rendered content plus `extracted_keywords` and `custom_bullets_report` |

Section order is fixed: Work Experience → Certifications → Education → Skills. There is no summary block. Default prefix is `tailored_resume`.

## CLI reference

| Flag | Applies to | Default | Meaning |
| --- | --- | --- | --- |
| `--api-key` | both | `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `OPENCODE_API_KEY` | Bearer token |
| `--base-url` | both | `OPENAI_BASE_URL` / `OPENROUTER_BASE_URL` / `OPENCODE_BASE_URL`, else `https://api.openai.com/v1` | Endpoint or shorthand |
| `--model` | both | `OPENAI_MODEL` / `OPENROUTER_MODEL` / `OPENCODE_MODEL`, else `gpt-4o` | Model ID |
| `-o, --output` | `ingest` | `profile.yaml` | Profile path to write |
| `-p, --profile` | `tailor` | `profile.yaml` | Profile path to read |
| `-j, --jd` | `tailor` | required | Job description file |
| `-o, --outdir` | `tailor` | `output/` | Output directory |
| `--name-prefix` | `tailor` | `tailored_resume` | Output filename prefix |
| `--custom-bullets` | `tailor` | `3` | Custom bullets to inject (integer ≥ 1) |

`-o` means different things per subcommand: profile path for `ingest`, output directory for `tailor`.

## Humanizer guarantees (`blader/humanizer`)

Every `tailor` run applies two stages:

1. **LLM pass** — rewrites drafted bullets to match `voice_profile.sample_bullets` and removes AI tells: *not only X, but also Y*, forced triads, unauthorized dashes, stock words (*delve*, *pivotal*, *bolstered*, *meticulously*), shallow `-ing` riders (*...ensuring...*), and `**Label:**` prefixes. Metrics, tool names, and extracted keywords are preserved.
2. **Deterministic pass** — `humanize_text_deterministic()` strips any surviving labels, curly quotes, unauthorized dashes, and `-ing` riders before rendering.

## Verify

```bash
python3 test_resume_gen.py
```

Offline suite (mocks the LLM) covering ingestion, merging, tailoring, DOCX/PDF rendering, pagination, and the CLI flags. Run it after modifying `resume_gen.py`.
