# AGENTS.md — Resume Generator (`resume_gen`)

Repo orientation. For the agent-facing workflow and flag reference, use `SKILL.md`.

## Layout

- **`resume_gen.py`** — single-file CLI (`ingest`, `tailor`) and importable module:
  - `_load_dotenv()`: loads `.env` from the current directory, then the script directory, without overwriting existing env vars.
  - `extract_text_from_file(path)`: `.txt`/`.md`/`.yaml`/`.yml` via `read_text`, `.docx` via stdlib `zipfile` + `xml.etree`, `.pdf` via `pypdf` else system `pdftotext`.
  - `_resolve_endpoint_and_payload(...)` & `call_llm_json(...)`: OpenAI-compatible requests; routes `opencode-go` / `opencode` model IDs to Chat Completions, Responses, Anthropic Messages, or Gemini, and sends `x-opencode-session`.
  - `ingest_resumes(...)`, `merge_profiles(...)`, `compute_voice_stats(...)`: LLM extraction into YAML; merging is idempotent — new roles/bullets/skills/education/certifications are appended, duplicate bullets dropped, existing `basics` and `voice_profile` values win, and extra fields on a role are kept.
  - `tailor_resume(...)`: Pass 1 extracts JD keywords and drafts `custom_bullet_count` custom bullets (default 3, CLI `--custom-bullets`, must be ≥ 1); Pass 2 is the `blader/humanizer` rewrite, followed by `humanize_text_deterministic(...)` cleanup; returned `skills` are filtered to profile skills ∪ extracted keywords.
  - `write_ats_docx(...)` & `write_ats_pdf(...)`: single-column output in Work Experience → Certifications → Education → Skills order, no summary section.
  - `build_parser()` / `main()`: argparse CLI; `_positive_int` validates `--custom-bullets`.
- **`SKILL.md`** — agent workflow, CLI reference, `.env` config.
- **`README.md`** — human quick start.
- **`test_resume_gen.py`** — offline suite; mocks the LLM, no network or API key needed.
- **`profile.yaml`** — user data, edited by hand; never rewrite it wholesale. **`output/`** — regenerable artifacts.

## Verification

Run `python3 test_resume_gen.py`; it prints `ALL TESTS PASSED`. Tests are plain functions, so a new one must also be called from the `__main__` block — there is no auto-discovery.

## Constraints

- Python 3.9+, stdlib plus `PyYAML`; `pypdf` optional. Don't add dependencies for a few lines.
- Keep the single-file design unless the user asks to split it.
