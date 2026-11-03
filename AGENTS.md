# AGENTS.md — Resume Generator (`resume_gen`)

Repo orientation. For the agent-facing workflow and flag reference, use `SKILL.md`.

## Layout

- **`resume_gen.py`** — single-file CLI (`ingest`, `tailor`) and importable module:
  - `_load_dotenv()`: loads `.env` from the current directory, then the script directory, without overwriting existing env vars.
  - `extract_text_from_file(path)`: `.txt`/`.md`/`.yaml`/`.yml` via `read_text`, `.docx` via stdlib `zipfile` + `xml.etree`, `.pdf` via `pypdf` else system `pdftotext`.
  - `_resolve_endpoint_and_payload(...)` & `call_llm_json(...)`: OpenAI-compatible requests; routes `opencode-go` / `opencode` model IDs to Chat Completions, Responses, Anthropic Messages, or Gemini, and sends `x-opencode-session`.
  - `--backend codex`: routes both commands and all model passes through `_call_codex(...)`, using saved CLI authentication, a temporary working directory, read-only sandboxing, and the CLI default model unless `--model` is explicit. `api` remains the default; `_parse_llm_json(...)` is shared by both backends.
  - `ingest_resumes(...)`, `merge_profiles(...)`, `compute_voice_stats(...)`: LLM extraction into YAML; merging is idempotent — new roles/bullets/skills/education/certifications are appended, duplicate bullets dropped, existing `basics` and `voice_profile` values win, and extra fields on a role are kept.
  - `tailor_resume(...)`: Pass 1 analyzes the job, selects/reorders content, and brainstorms custom bullets (default 3, integer ≥ 0), useful skill suggestions, and optional alternatives. `_working_profile` / `_selected_roles` attach stable IDs in memory and preserve profile job metadata/chronology. Pass 2 edits selected bullet text only; missing edits and lost numerical results fall back to the draft. `humanize_text_deterministic` normalizes formatting without deleting outcome clauses or applying stock-word bans. Skills are editorial selections, not evidence-filtered.
  - `write_ats_docx(...)` & `write_ats_pdf(...)`: single-column output in Certifications → Work Experience → Education → Skills order, no summary section. PDF uses exact Helvetica advances and balances pages across whole blocks; DOCX uses paragraph keep rules. Both wrap long role headings and put location/dates on a separate line.
  - `write_review_markdown(...)`: companion editing notes distinguish included proposals/expansions from optional alternatives. Reports also include job analysis, selection rationale, and generation limitations.
  - `build_parser()` / `main()`: argparse CLI; `_nonnegative_int` validates `--custom-bullets`. Render DOCX/PDF/JSON/Markdown into temporary files before replacing previous outputs.
- **`SKILL.md`** — agent workflow, CLI reference, `.env` config.
- **`README.md`** — human quick start.
- **`test_resume_gen.py`** — offline suite; mocks the LLM, no network or API key needed.
- **`profile.yaml`** — user data, edited by hand; never rewrite it wholesale. **`output/`** — regenerable artifacts.

## Verification

Run `python3 test_resume_gen.py`; it prints `ALL TESTS PASSED`. Tests are plain functions, so a new one must also be called from the `__main__` block — there is no auto-discovery.

## Constraints

- Python 3.9+, stdlib plus `PyYAML`; `pypdf` optional. Don't add dependencies for a few lines.
- Keep the single-file design unless the user asks to split it.
- Brainstorming is the priority. The user verifies and edits content after generation; do not introduce evidence restrictions or pre-generation approval gates. Keep custom proposals in the delivered draft and optional alternatives in the report.
