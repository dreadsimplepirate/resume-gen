# Resume Generator

Draft tailored resumes and brainstorm what could strengthen them. Your editable profile supplies career context; the generator selects relevant achievements, proposes custom bullets, and exports DOCX, PDF, and editing notes. Review, verify, and revise the generated content afterward.

## Setup

Python 3.9+ and PyYAML. PDF input also requires optional `pypdf` or system `pdftotext`:

```bash
pip install pyyaml pypdf
```

Choose a backend. With Codex CLI installed, sign in with `codex login`; check with `codex login status`. The CLI backend uses its saved authentication/configuration and needs no resume-generator API key. Your account's access and usage limits apply.

For the API backend, copy `.env.example` to `.env` and set the key, endpoint, and model. `OPENAI_*`, `OPENROUTER_*`, and `OPENCODE_*` variables are supported. Existing environment variables take precedence over `.env`, and explicit command flags take precedence over both.

## Build the profile

```bash
python3 resume_gen.py --backend codex ingest my_resume.pdf older_resume.docx -o profile.yaml
```

Accepts PDF, DOCX, TXT, MD, YAML, and YML. Re-ingestion merges with the existing profile. Open `profile.yaml` to add experience or refine the writing samples; tailoring never rewrites it.

## Generate a tailored draft

Save the job description to `jd.txt`, then run:

```bash
python3 resume_gen.py --backend codex tailor \
  -p profile.yaml -j jd.txt -o output/ \
  --name-prefix target_role --custom-bullets 3
```

Put global flags (`--backend`, `--model`, `--api-key`, `--base-url`) before the subcommand. Omit `--model` to use Codex's configured default. API model settings in `.env` do not select the Codex model. Each pass is a separate text-only CLI task, not a continuation of this chat, with a 600-second timeout.

To use your configured HTTP provider instead, omit `--backend codex` or select `--backend api`. That remains the default backend.

`--custom-bullets` accepts zero or more, default 3. Custom bullets stay in the draft; optional alternatives stay in the editing report. The profile is context for brainstorming, so the generator may propose experience and skills not already recorded there. You make the final decisions afterward.

## Review the results

- `output/target_role.docx`: editable single-column resume.
- `output/target_role.pdf`: resume with wrapped headings, whole content blocks, and balanced pages.
- `output/target_role_report.json`: selected content and generation details.
- `output/target_role_review.md`: positioning, job themes, included proposals and expansions, alternatives, and details worth adding during editing.

The generator analyzes the actual role rather than relying only on keywords. Its second pass edits selected text; missing style edits fall back to the draft. Formatting cleanup preserves meaningful outcome clauses and numerical results. Both exports use the same selected content in Certifications → Work Experience → Education → Skills order, with no summary. Degree and credential order can be tailored without deleting entries.

Check the documents visually before sending. PDF uses built-in WinAnsi fonts and warns about unsupported characters; DOCX preserves Unicode. No ATS score or hiring outcome is guaranteed.

## Useful flags

| Flag | Behavior |
| --- | --- |
| `--backend api|codex` | Global; default `api` |
| `--model MODEL_ID` | Global; explicit model override |
| `--api-key KEY`, `--base-url URL` | Global; HTTP API settings |
| `-p PROFILE`, `-j JD` | Tailoring inputs; profile defaults to `profile.yaml` |
| `-o PATH` | Ingest: profile file; tailor: output directory |
| `--name-prefix PREFIX` | Default `tailored_resume` |
| `--custom-bullets N` | Integer ≥ 0; default 3 |

## Checks

```bash
python3 test_resume_gen.py
```

The offline suite mocks model calls and checks drafting/editing fallbacks, proposals, both backends, reports, exports, and pagination. Plain tests must be called from its `__main__` block. Actual model runs and visual inspection are reported separately.
