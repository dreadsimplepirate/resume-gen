# Resume Generator (`resume_gen.py`)

One script. Two commands. No clutter — that be the whole treasure map.

Run `ingest` and this scallywag reads yer old resumes and stows 'em in a plain `profile.yaml` ye can open, edit, and keep: yer real experience, not a black box. Run `tailor` and it reads the job description, plucks out the keywords that matter, slips in three custom bullets (change the count with `--custom-bullets 5` if ye want a bigger broadside), scrapes off the AI-sounding bilge so it sounds like ye wrote it, and hands back clean, ATS-friendly `.docx` and `.pdf` files in seconds flat.

No server, no database, no framework — just Python, PyYAML, a single script ye can read end to end, and `pypdf` only if yer PDFs need reading.

## 1. Setup

Requires Python 3.9+ and `PyYAML`. Reading PDF resumes additionally needs `pypdf` or the system `pdftotext` binary:

```bash
pip install pyyaml pypdf
```

Create a `.env` file in this folder (or copy the example):

```bash
cp .env.example .env
chmod 600 .env   # keep the API key readable only by you
```

Edit `.env` with your API key and preferred model:

```dotenv
OPENCODE_API_KEY="your-api-key-here"
OPENCODE_BASE_URL="opencode-go"
OPENCODE_MODEL="MiMo-V2.6-Pro"
```

You can also use standard OpenAI or OpenRouter keys by setting `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` or `OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL` / `OPENROUTER_MODEL`. Real environment variables win over `.env`, and `--api-key`, `--base-url`, `--model` win over both.

## 2. Build Your Experience Library (Run Once)

Pass one or more of your existing resumes (`.pdf`, `.docx`, `.txt`, or `.md`) to `ingest`:

```bash
python3 resume_gen.py ingest my_resume.pdf older_resume.docx -o profile.yaml
```

This creates **`profile.yaml`** — a clean text file containing your contact info, work history, education, skills, and writing style notes.
- Open `profile.yaml` in any text editor to review or tweak your details, add missing phone/email info, or refine bullets.
- If you run `ingest` again later with another resume, it merges the new roles and bullets in without erasing your manual edits to `basics` or `voice_profile`.

## 3. Tailor Your Resume for a Job

1. Save the job description to a file (`.txt`, `.md`, `.pdf`, or `.docx`).
2. Run `tailor` against your existing `profile.yaml`:

```bash
python3 resume_gen.py tailor -p profile.yaml -j jd.txt -o output/ --name-prefix acme_security
```

`-p` must point to an existing profile — `tailor` never creates one.

### What You Get in `output/`

- **`output/acme_security.pdf`** — A clean, ATS-readable PDF with centered header, right-aligned dates, and `Work Experience` → `Certifications` → `Education` → `Skills`. It paginates automatically when the content runs past one page.
- **`output/acme_security.docx`** — An editable Word version of the same resume if you want to make final hand edits.
- **`output/acme_security_report.json`** (also printed to the terminal) — The exact ATS keywords extracted from the job description and the **custom bullets** that were added to your roles, so you can check each claim before applying.

If `--name-prefix` is omitted, files are written as `output/tailored_resume.{docx,pdf}` and `output/tailored_resume_report.json`.

## Useful Options

- `--custom-bullets <n>` (default: `3`): Choose how many new custom bullets to inject across your existing roles, e.g. `--custom-bullets 5`. Must be at least 1.
- `--model <model-name>`: Override `.env` for a single run, e.g. `--model gpt-4o`. Any model ID your endpoint accepts works.
- `--base-url <url>`: Override the endpoint — a full OpenAI-compatible URL, or the shorthands `opencode-go`, `opencode`, and `openrouter`.
- `--api-key <key>`: Override the key from `.env`.
- `-p`, `-j`, `-o`, `--name-prefix`: Profile path, job description path, output directory (default `output/`), and filename prefix. `-o` means the profile path for `ingest` and the output directory for `tailor`.

## Notes

- The report's custom bullets are written by the model to target the job description; they are plausible phrasing, not verified facts. Review them against your actual experience before sending.
- Run `python3 test_resume_gen.py` after editing the script — it exercises ingestion, tailoring, and both exports offline with a mocked LLM.
