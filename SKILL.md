---
name: resume-gen
description: Draft tailored resumes and brainstorm role-specific experience to include, using an editable career profile and a job posting. Produces DOCX, PDF, and editing notes for the user to verify and revise afterward. Use for resume tailoring, resume-profile ingestion, and resume artifact review; explaining a job posting alone does not require generation.
---

# Resume drafting and brainstorming

Use `resume_gen.py` to turn career context and a specific job posting into a persuasive, editable draft. Brainstorm useful adjacent experience rather than treating the profile as an exhaustive list. The user verifies, edits, and selects proposals after generation.

## Workflow

1. **Read the target and career context.** Use the exact posting or supplied JD text. For a URL, retrieve the job and save its text locally with the URL and retrieval date. If unavailable, use a reproduction tied to the exact job ID and identify that source limitation. Ask for missing JD text only when no usable source is available. Do not substitute a different job.
2. **Choose positioning.** Identify the actual work, business context, and important required/preferred qualifications. Use `profile.yaml` for strengths, career chronology, and voice. Make the first three bullets of the most relevant recent role address the central job responsibilities with concrete scope and outcomes. Use important exact phrases naturally, with useful acronym expansions; keep past job titles intact. Do not rewrite the profile wholesale.
3. **Generate and brainstorm.** Run `tailor`. Deliver the requested custom bullets in the resume; contextual proposals may include responsibilities or tools absent from the profile. Do not require a verification interview, confirmation, or approval before drafting. Preserve existing metrics; use placeholders in optional variants when numerical detail is needed. Keep degrees and certifications out of Skills.
4. **Review the editorial choices.** Read the JSON and Markdown reports. Prioritize relevant accomplishments, integrate useful custom bullets near the top, consolidate repeated skills, and compress unrelated older roles. Aim for roughly 12–18 skills as a starting point, not a quota. Preserve chronology and requested custom content. Review substantive expansions of ordinary bullets as well as custom bullets in the editing notes.
5. **Inspect both documents.** Render every page of DOCX and PDF using available document/PDF tools; compare extracted content with the report separately. Check heading/date separation, readability, whole bullets, Education grouping, and page balance. Prefer two balanced pages to one crowded page plus a fragment. Never shrink text merely to force one page.
6. **Repair demonstrated issues and deliver.** Make one focused editorial/layout repair when needed and recheck affected artifacts. If a prerequisite is unavailable, deliver the usable draft and identify the unverified part. Include the resume files, concise positioning rationale, editing notes, and the generated-change checklist below. Clearly distinguish included proposals from optional alternatives. Do not promise an ATS score or hiring outcome.

## Flag generated changes in the conversation

After every generation, include a visible **Generated changes to review** section in the final chat reply. Read `changes_report` from the final JSON; a file link alone is insufficient. This comparison includes unflagged rewrites as well as model-flagged proposals.

- For each custom/new/expanded bullet, show the employer, bullet ID, exact tailored wording, and specific facts or details for the user to check. Include original wording when available.
- For other rewritten bullets, show original → tailored wording or the exact changed phrases, with the employer and ID. Do not assume a rewrite is factual expansion or omit it merely because `is_expanded` is false.
- List every added or reworded skill term together. Some may be aliases for existing skills; do not describe them automatically as invented experience.
- Group longer lists by employer rather than silently truncating them. Omit unchanged content and keep optional alternatives separate from changes already included in the resume.
- Let the user refer to bullet IDs when requesting corrections. Flagging is for review after generation; do not pause or require confirmation before delivering the draft.

Also show **Optional omissions for later editing** in the conversation report, using `omission_suggestions`. For each suggestion quote the credential or degree, explain why it may add less value for this specific role, and identify what could receive more emphasis instead. These are optional editing recommendations: retain every credential and degree in the delivered documents and preserve employment history. Do not add omission flags, remove entries automatically, or pause for a decision. If there is no useful omission, say so briefly. Do not infer that a credential has expired solely from its date.

Assess final job alignment separately: check that the most important requirements have concrete examples, key phrases survive editing, and bullets communicate ownership and results. A keyword mention alone does not demonstrate a qualification. Clean text extraction and formatting checks improve readability but are not a test of a particular employer's ATS ranking.

A neighboring request to explain a posting should be answered directly without generating resumes or modifying the profile.

## Setup and backends

Python 3.9+ and `PyYAML`. PDF input additionally requires optional `pypdf` or system `pdftotext`.

Global flags go **before** `ingest` or `tailor`.

### Codex CLI

```bash
python3 resume_gen.py --backend codex tailor -p profile.yaml -j jd.txt -o output/ --name-prefix target_role
python3 resume_gen.py --backend codex ingest sample.pdf -o profile.yaml
```

Uses installed Codex CLI authentication and configuration. Check `codex login status`; sign in with `codex login` if needed. No resume-generator API key is required. Omit `--model` for the CLI default; an explicit `--model` overrides it. API model environment variables do not select the Codex model.

Each pass runs a separate text-only task in a temporary directory with read-only sandboxing. It receives supplied prompts/content, not this chat's history. Allow up to 600 seconds per call. The script does not automatically retry CLI failures.

### HTTP API

The default backend is `api`. Configure `.env` or existing environment variables:

```dotenv
OPENCODE_API_KEY="your-key"
OPENCODE_BASE_URL="opencode-go"
OPENCODE_MODEL="your-model"
```

`OPENAI_*` and `OPENROUTER_*` are also supported. Existing environment variables win over `.env`; CLI overrides win over both. Base URLs accept `opencode-go`, `opencode`, `openrouter`, or an OpenAI-compatible URL.

## Ingestion

```bash
python3 resume_gen.py ingest resume1.pdf resume2.docx -o profile.yaml
```

Accepts PDF, DOCX, TXT, MD, YAML, and YML. Re-ingestion merges rather than replacing existing basics/voice edits. The profile can be curated manually; role bullets and voice samples guide generation. Voice samples without an assigned role are style context, not automatically part of a particular job.

## Tailoring

```bash
python3 resume_gen.py --backend codex tailor \
  -p profile.yaml -j jd.txt -o output/ \
  --name-prefix acme_security --custom-bullets 3
```

`-p` must exist. `-j` accepts the same file types as ingestion. `--custom-bullets` is an integer ≥ 0, default 3; zero disables the request for additional custom bullets. Report a count shortfall without blocking the delivered draft.

The first pass analyzes the role, selects/reorders content, and brainstorms included proposals and optional alternatives. The second edits selected bullet text only. Stable IDs preserve selection and order; missing style content falls back to the draft. Cleanup normalizes formatting without deleting outcome clauses or enforcing word bans. The profile's employment metadata stays intact. Skills are selected editorially, including useful JD suggestions.

## Outputs and editing notes

For prefix `target_role`:

- `output/target_role.docx` — editable resume.
- `output/target_role.pdf` — single-column resume with balanced pagination.
- `output/target_role_report.json` — selected content, `job_analysis`, `changes_report`, `omission_suggestions`, `custom_bullets_report`, `brainstorming`, `editorial_notes`, and `generation_notes`.
- `output/target_role_review.md` — positioning, job themes, included proposals/expansions, optional alternatives, and details to consider afterward.

Section order remains Certifications → Work Experience → Education → Skills, with no summary. All education and credential entries remain; their order can be tailored. The PDF's built-in fonts use WinAnsi; use DOCX for unsupported characters and report the limitation.

## Flag reference

| Flag | Scope | Default / behavior |
| --- | --- | --- |
| `--backend api|codex` | global | `api` |
| `--model` | global | API model env vars or `gpt-4o`; Codex CLI default |
| `--api-key` | global | API key env vars; not required for Codex |
| `--base-url` | global | Configured API endpoint; API only |
| `-p, --profile` | tailor | `profile.yaml` |
| `-j, --jd` | tailor | Required local JD file |
| `-o, --output` | ingest | `profile.yaml` |
| `-o, --outdir` | tailor | `output/` |
| `--name-prefix` | tailor | `tailored_resume` |
| `--custom-bullets` | tailor | 3, integer ≥ 0 |

## Verification after code changes

Run `python3 test_resume_gen.py`; all plain test functions must be called from its `__main__` block. Offline checks validate behavior and failures without API keys. Visual inspection and actual model-backed runs are separate checks; report which were performed. See `skill-evaluation.md` for normal, sparse-profile, failure, and neighboring-request scenarios.
