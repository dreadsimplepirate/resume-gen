#!/usr/bin/env python3
"""
resume_gen.py - ATS-friendly resume matcher, custom experience generator, and humanizer.

Commands:
  ingest  Parse sample resumes (.pdf, .docx, .txt, .md) into an editable profile.yaml library.
  tailor  Match profile.yaml to a job description, add N custom bullets (--custom-bullets, default 3), humanize, and export .docx + .pdf.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import yaml


def _load_dotenv() -> None:
    """Load key=value pairs from .env in CWD or script directory into os.environ (without overwriting)."""
    for env_path in (Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"):
        if env_path.is_file():
            for raw_line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                line = re.sub(r"^export\s+", "", line)
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if val[:1] in {"'", '"'}:
                    quote = val[0]
                    end = val.find(quote, 1)
                    val = val[1:end] if end != -1 else val[1:]
                else:
                    # Unquoted value: '#' at the start or after a space begins a comment.
                    val = re.sub(r"(?:^|\s+)#.*$", "", val).strip()
                if key and key not in os.environ:
                    os.environ[key] = val


_load_dotenv()

DEFAULT_MODEL = (
    os.environ.get("OPENAI_MODEL")
    or os.environ.get("OPENROUTER_MODEL")
    or os.environ.get("OPENCODE_MODEL")
    or "gpt-4o"
)
DEFAULT_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL")
    or os.environ.get("OPENROUTER_BASE_URL")
    or os.environ.get("OPENCODE_BASE_URL")
    or ("https://openrouter.ai/api/v1" if os.environ.get("OPENROUTER_API_KEY") else "https://api.openai.com/v1")
)
SESSION_ID = f"ses_{uuid.uuid4().hex[:16]}"

# blader/humanizer §12 stock AI words & §15 shallow -ing riders
AI_WORD_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmeticulously\s+", re.IGNORECASE), ""),
    (re.compile(r"\bseamlessly\s+", re.IGNORECASE), ""),
    (re.compile(r"\bpivotal\s+", re.IGNORECASE), ""),
    (re.compile(r"\bcrucial\s+", re.IGNORECASE), "core "),
    (re.compile(r"\bgroundbreaking\s+", re.IGNORECASE), ""),
    (re.compile(r"\bvibrant\s+", re.IGNORECASE), ""),
    (re.compile(r"\bindelible\s+", re.IGNORECASE), ""),
    (re.compile(r"\bdelved into\b", re.IGNORECASE), "analyzed"),
    (re.compile(r"\bdelve into\b", re.IGNORECASE), "analyze"),
    (re.compile(r"\bbolstered\b", re.IGNORECASE), "strengthened"),
    (re.compile(r"\bunderscored\b", re.IGNORECASE), "showed"),
    (re.compile(r"\bshowcased\b", re.IGNORECASE), "demonstrated"),
    (re.compile(r"\bserves as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bserved as\b", re.IGNORECASE), "was"),
    (re.compile(r"\bfunctions as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bfunctioned as\b", re.IGNORECASE), "was"),
    (re.compile(r"\bstands as a testament to\b", re.IGNORECASE), "shows"),
]

SHALLOW_ING_RIDER_RE = re.compile(
    r",\s*(?:thereby\s+|ultimately\s+)?(?:ensuring|highlighting|underscoring|emphasizing|"
    r"fostering|cultivating|showcasing|reflecting|symbolizing|encompassing|"
    r"contributing to)\b.*?(?=[.!?](?:\s|$)|;|$)",
    re.IGNORECASE,
)

NOT_ONLY_BUT_ALSO_RE = re.compile(
    r"\bnot\s+(?:only|just|merely)\s+([^,;]+?),?\s+but\s+(?:also\s+)?",
    re.IGNORECASE,
)

BOLD_LABEL_PREFIX_RE = re.compile(r"^\s*\*\*[^*]{1,40}?:\*\*\s*")
XML_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def extract_text_from_file(path: Path) -> str:
    """Extract plain text from .txt, .md, .docx, or .pdf files."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".yaml", ".yml"}:
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
        except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            raise ValueError(f"Invalid or corrupt .docx file: {path}") from exc
        paragraphs: list[str] = []
        for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            texts = [
                t.text
                for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                if t.text
            ]
            if texts:
                paragraphs.append("".join(texts).strip())
        return "\n".join(p for p in paragraphs if p)

    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            pass
        if shutil.which("pdftotext"):
            res = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout
        raise RuntimeError(
            f"Cannot parse PDF '{path}': install 'pypdf' or system 'pdftotext'."
        )

    raise ValueError(f"Unsupported file format: {path} (expected .pdf, .docx, .txt, .md)")


def _resolve_endpoint_and_payload(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    api_key: str = "",
) -> tuple[str, dict[str, Any], str]:
    """
    Resolve URL, JSON payload, and API family ('chat', 'responses', 'anthropic', 'gemini').
    Supports OpenAI, OpenRouter, OpenCode Console / OpenCode Go, and any OpenAI-compatible URL.
    """
    b = base_url.rstrip("/")
    if b == "openrouter" or (b == "https://api.openai.com/v1" and api_key.startswith("sk-or-")):
        b = "https://openrouter.ai/api/v1"
    m = re.sub(r"^(?:opencode-go|opencode)/", "", model.strip()).lower()
    opencode_base = {
        "opencode-go": "https://opencode.ai/inference/go",
        "https://opencode.ai/inference/go": "https://opencode.ai/inference/go",
        "opencode": "https://opencode.ai/inference",
        "https://opencode.ai/inference": "https://opencode.ai/inference",
    }.get(b)
    if opencode_base:
        model = m
        is_go = opencode_base.endswith("/go")
        if m.startswith(("gpt-", "grok-", "muse-")):
            b = f"{opencode_base}/openai/v1/responses"
        elif m.startswith("gemini-"):
            b = f"{opencode_base}/google/v1beta/models/{model}:generateContent"
        elif (
            m.startswith("claude-")
            or (m.startswith("qwen") and (is_go or m != "qwen3.8-max"))
            or (is_go and m == "minimax-m3")
        ):
            b = f"{opencode_base}/anthropic/v1/messages"
        else:
            b = f"{opencode_base}/openai/v1/chat/completions"

    if b.endswith("/responses"):
        return (
            b,
            {
                "model": model,
                "instructions": system_prompt,
                "input": user_prompt,
                "temperature": temperature,
            },
            "responses",
        )
    if b.endswith("/messages"):
        return (
            b,
            {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": temperature,
            },
            "anthropic",
        )
    if ":generateContent" in b or "/google/v1beta/models/" in b:
        url = b if ":generateContent" in b else f"{b}:{model}:generateContent" if b.endswith("/models") else f"{b}:generateContent"
        return (
            url,
            {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": temperature},
            },
            "gemini",
        )

    url = b if b.endswith("/chat/completions") else f"{b}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if "api.openai.com" in url:
        payload["response_format"] = {"type": "json_object"}
    return url, payload, "chat"


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call OpenAI, OpenRouter, OpenCode Inference, or compatible endpoints and return parsed JSON."""
    if not api_key:
        raise RuntimeError(
            "Missing LLM API key. Set OPENAI_API_KEY / OPENROUTER_API_KEY / OPENCODE_API_KEY or pass --api-key."
        )
    url, payload, family = _resolve_endpoint_and_payload(
        base_url, model, system_prompt, user_prompt, temperature, api_key=api_key
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "resume-gen/1.0",
    }
    if "opencode.ai" in url:
        headers["x-opencode-session"] = SESSION_ID
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    for attempt in range(3):
        try:
            # shortcut: 600s read timeout; reasoning models can exceed 120s on a full profile+JD prompt
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"LLM API error ({exc.code}): {err_body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"LLM network error: {getattr(exc, 'reason', exc)}") from exc
        time.sleep(2**attempt)

    content: str | None = None
    if family == "responses":
        content = body.get("output_text")
        if not content:
            for item in body.get("output") or []:
                for part in item.get("content") or []:
                    if part.get("type") in {"output_text", "text"} and part.get("text"):
                        content = part["text"]
                        break
    elif family == "anthropic":
        for block in body.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                content = block["text"]
                break
    elif family == "gemini":
        candidates = body.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        content = parts[0].get("text") if parts else None
    else:
        choices = body.get("choices") or []
        content = (choices[0].get("message") or {}).get("content") if choices else None

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned an empty response.")

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise RuntimeError("LLM response root must be a JSON object.")
    return parsed


def compute_voice_stats(roles: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute deterministic voice metrics from extracted resume bullets."""
    bullets: list[str] = [
        b.strip()
        for role in roles
        for b in (role.get("bullets") or [])
        if isinstance(b, str) and b.strip()
    ]
    if not bullets:
        return {"uses_dashes": False, "avg_words_per_bullet": 16, "sample_bullets": []}
    dash_count = sum(1 for b in bullets if ("—" in b or "–" in b or " -- " in b))
    word_counts = [len(b.split()) for b in bullets]
    return {
        "uses_dashes": (dash_count / len(bullets)) >= 0.25,
        "avg_words_per_bullet": round(sum(word_counts) / len(word_counts)),
        "sample_bullets": bullets[:6],
    }


def _bullet_key(text: Any) -> str:
    return re.sub(r"\W+", " ", str(text).lower()).strip()


def _text_overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


def merge_profiles(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge newly extracted resume profile data into an existing profile without losing user edits."""
    def _dedup_strs(cur: list[Any], new: list[Any]) -> list[str]:
        out = [str(x).strip() for x in cur if str(x).strip()]
        seen = {x.lower() for x in out}
        for item in new:
            s = str(item).strip() if item else ""
            if s and s.lower() not in seen:
                out.append(s)
                seen.add(s.lower())
        return out

    merged = dict(existing or {})
    basics = dict(merged.get("basics") or {})
    for k, v in (incoming.get("basics") or {}).items():
        if k == "links":
            basics["links"] = _dedup_strs(basics.get("links") or [], v or [])
        elif v and not basics.get(k):
            basics[k] = v
    merged["basics"] = basics

    merged["skills"] = _dedup_strs(merged.get("skills") or [], incoming.get("skills") or [])
    merged["certifications"] = _dedup_strs(
        merged.get("certifications") or [], incoming.get("certifications") or []
    )

    roles_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    role_order: list[tuple[str, str]] = []
    for r in (merged.get("roles") or []) + (incoming.get("roles") or []):
        if not isinstance(r, dict):
            continue
        key = (
            str(r.get("company", "")).strip().lower(),
            str(r.get("title", "")).strip().lower(),
        )
        if key not in roles_by_key:
            # Keep any extra fields the user added to this role; only bullets are merged.
            roles_by_key[key] = {**r, "bullets": []}
            role_order.append(key)
        target = roles_by_key[key]
        if not target.get("location") and r.get("location"):
            target["location"] = r["location"]
        if not target.get("dates") and r.get("dates"):
            target["dates"] = r["dates"]
        # Compare against existing bullets: exact text, substring, or near-identical wording.
        existing_norms = [
            (f" {_bullet_key(b)} ", set(_bullet_key(b).split())) for b in target["bullets"]
        ]
        for b in r.get("bullets") or []:
            key = _bullet_key(b)
            words = set(key.split())
            if not key:
                continue
            if any(
                f" {key} " in padded or _text_overlap(words, other) >= 0.8
                for padded, other in existing_norms
            ):
                continue
            target["bullets"].append(str(b).strip())
            existing_norms.append((f" {key} ", words))

    merged["roles"] = [roles_by_key[k] for k in role_order]

    edu_list = list(merged.get("education") or [])
    seen_edu = {
        (str(e.get("school", "")).lower().strip(), str(e.get("dates", "")).lower().strip())
        for e in edu_list
    }
    for e in incoming.get("education") or []:
        if not isinstance(e, dict):
            continue
        ekey = (
            str(e.get("school", "")).lower().strip(),
            str(e.get("dates", "")).lower().strip(),
        )
        if ekey not in seen_edu:
            edu_list.append(e)
            seen_edu.add(ekey)
    merged["education"] = edu_list

    # Compute baseline stats, then overlay incoming LLM tone and any existing manual voice edits
    computed_voice = compute_voice_stats(merged["roles"])
    existing_voice = dict(merged.get("voice_profile") or {})
    incoming_voice = dict(incoming.get("voice_profile") or {})
    voice = {
        **computed_voice,
        **incoming_voice,
        **existing_voice,
        "avg_words_per_bullet": computed_voice["avg_words_per_bullet"],
    }
    merged["voice_profile"] = voice
    return merged


def _write_atomic(path: Path, data: str) -> None:
    """Write text via a temp file so an interrupted run never truncates the original."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def ingest_resumes(
    input_paths: list[Path],
    output_path: Path,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Parse one or more sample resumes and create/update the YAML experience library."""
    raw_chunks = [
        f"--- RESUME FILE: {p.name} ---\n{extract_text_from_file(p)}"
        for p in input_paths
    ]
    system_prompt = (
        "You extract structured work experience libraries from raw resume text. "
        "Preserve the user's exact wording, metrics, and technical terminology inside bullets. "
        "Deduplicate identical roles across multiple sample resumes while keeping all distinct bullets. "
        "Return strict JSON matching this schema:\n"
        "{\n"
        '  "basics": {"name": "", "email": "", "phone": "", "location": "", "links": []},\n'
        '  "voice_profile": {"tone": "Short description of verb tense, directness, metric style"},\n'
        '  "skills": ["skill1", "skill2"],\n'
        '  "roles": [\n'
        '    {"company": "", "title": "", "location": "", "dates": "", "bullets": ["verbatim bullet"]}\n'
        "  ],\n"
        '  "education": [{"school": "", "degree": "", "dates": ""}]\n'
        "}"
    )
    extracted = call_llm_json(
        system_prompt,
        "Extract and merge all experiences from these sample resumes:\n\n" + "\n\n".join(raw_chunks),
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.1,
    )

    existing: dict[str, Any] = {}
    if output_path.exists():
        existing = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}

    final_profile = merge_profiles(existing, extracted)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header_comment = (
        "# Human-Editable Work Experience Library (generated by resume_gen.py)\n"
        "# Feel free to edit bullets, skills, roles, or voice_profile before running `tailor`.\n\n"
    )
    _write_atomic(
        output_path,
        header_comment + yaml.safe_dump(final_profile, sort_keys=False, allow_unicode=True, width=100),
    )
    return final_profile


def humanize_text_deterministic(text: str, *, allow_dashes: bool = False) -> str:
    """
    Deterministic post-pass enforcing core blader/humanizer rules:
    - §1: Remove 'not only X, but also Y' staging contrasts
    - §8: Replace em/en dashes and spaced double-hyphens unless the writer's sample uses them
    - §12: Replace overused AI words
    - §15: Strip shallow trailing -ing riders ('...ensuring...', '...highlighting...', etc.)
    - §19: Strip decorative '**Label:**' prefixes
    - §21: Convert curly quotes to straight quotes
    """
    s = text.strip()
    s = re.sub(r"^[•\-*]\s+", "", s)
    s = BOLD_LABEL_PREFIX_RE.sub("", s)
    s = s.replace("**", "")
    s = s.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    s = NOT_ONLY_BUT_ALSO_RE.sub(r"\1 and ", s)
    if not allow_dashes:
        s = re.sub(r"\s*(?:—|–)\s*|\s+--\s+", ", ", s)
    s = SHALLOW_ING_RIDER_RE.sub("", s)
    for pattern, repl in AI_WORD_REPLACEMENTS:
        s = pattern.sub(repl, s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*,+", ",", s)
    s = re.sub(r",\s*([.!?])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,")
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    # Capitalize new sentences, but not after short abbreviations like "e.g." or "etc."
    s = re.sub(
        r"(?<!e\.g)(?<!i\.e)(?<!etc)(?<!U\.S)(?<!vs)([.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        s,
    )
    if s and s[-1] not in ".!?":
        s += "."
    return s


def _bullet_score(words: set[str], bullet: dict[str, Any]) -> float:
    return _text_overlap(words, set(_bullet_key(bullet.get("text", "")).split()))


def _match_draft_bullet(text: Any, draft_bullets: list[Any], index: int) -> dict[str, Any]:
    """Find the draft bullet this text came from: exact, then best word overlap, then position."""
    key = _bullet_key(text)
    for db in draft_bullets:
        if isinstance(db, dict) and _bullet_key(db.get("text", "")) == key:
            return db
    words = set(key.split())
    best: dict[str, Any] = {}
    best_score = 0.0
    for db in draft_bullets:
        if not isinstance(db, dict):
            continue
        score = _bullet_score(words, db)
        if score > best_score:
            best, best_score = db, score
    index_bullet = (
        draft_bullets[index] if index < len(draft_bullets) and isinstance(draft_bullets[index], dict) else {}
    )
    # Near-tie: shared phrasing makes two bullets look equally similar, so trust the position instead.
    if index_bullet and best_score - _bullet_score(words, index_bullet) < 0.1:
        return index_bullet
    if best_score >= 0.5:
        return best
    return index_bullet or {}


def _role_key(role: dict[str, Any]) -> tuple[str, str]:
    return (
        str(role.get("company", "")).strip().lower(),
        str(role.get("title", "")).strip().lower(),
    )


def _match_draft_role(role: dict[str, Any], draft_roles: list[Any], index: int) -> dict[str, Any]:
    """Find the draft role this role came from: company + title first, position only as a fallback."""
    key = _role_key(role)
    for dr in draft_roles:
        if isinstance(dr, dict) and _role_key(dr) == key:
            return dr
    if index < len(draft_roles) and isinstance(draft_roles[index], dict):
        return draft_roles[index]
    return {}


def tailor_resume(
    profile: dict[str, Any],
    jd_text: str,
    *,
    custom_bullet_count: int = 3,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """
    Two-pass LLM tailoring pipeline:
    Pass 1: Extract ATS keywords from JD, adapt existing bullets, and draft `custom_bullet_count` custom JD-matched bullets.
    Pass 2: Humanizer pass (blader/humanizer rules) + deterministic post-filter.
    """
    if custom_bullet_count < 1:
        raise ValueError(f"custom_bullet_count must be 1 or greater, got {custom_bullet_count}")
    voice_profile = profile.get("voice_profile") or {}
    allow_dashes = bool(voice_profile.get("uses_dashes", False))

    pass1_system = (
        "You are an expert ATS resume strategist and writer.\n"
        "Given a candidate's experience library (profile) and a target Job Description (JD):\n"
        "1. Extract the top 10-15 high-value ATS keywords/phrases from the JD (hard skills, tools, methods, domain terms).\n"
        "2. Reorder and augment the candidate's skills list to front-load exact JD keyword matches. "
        "Certifications, licenses, and degrees are NOT skills; keep them out of `skills` because they render in their own section.\n"
        "3. For each work role, select the strongest existing bullets and lightly adjust phrasing to match JD terminology "
        "while preserving the candidate's original metrics, scope, and voice.\n"
        f"4. Draft EXACTLY {custom_bullet_count} brand-new custom experience "
        f"bullet{'' if custom_bullet_count == 1 else 's'} (`is_custom: true`) into the most relevant existing "
        "work role(s). Each custom bullet must directly target high-priority JD keywords "
        "not fully covered by the original bullets, fit naturally within that role's domain, and match the user's writing style.\n"
        "Return strict JSON with this schema:\n"
        "{\n"
        '  "extracted_keywords": ["keyword1", "keyword2"],\n'
        '  "skills": ["skill1", "skill2"],\n'
        '  "roles": [\n'
        "    {\n"
        '      "company": "", "title": "", "location": "", "dates": "",\n'
        '      "bullets": [\n'
        '        {"text": "bullet text", "is_custom": false, "matched_keywords": ["kw1"]}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    pass1_user = (
        f"CANDIDATE PROFILE:\n{yaml.safe_dump(profile, sort_keys=False)}\n\n"
        f"TARGET JOB DESCRIPTION:\n{jd_text}"
    )
    draft = call_llm_json(
        pass1_system,
        pass1_user,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.3,
    )

    pass2_system = (
        "You are the Humanizer editor (based on blader/humanizer). "
        "Rewrite AI-sounding resume bullets so they read like the candidate's real writing sample, not a chatbot.\n"
        "STRICT HUMANIZER RULES:\n"
        "1. Voice Priority: Match the candidate's sample_bullets in sentence length, directness, verb choice, and rhythm.\n"
        "2. §1 No 'Not X, but Y' contrasts: Remove 'not only X, but also Y' or 'rather than'. State the outcome directly.\n"
        "3. §6 No Forced Triads: Replace rhythmic 3-item filler ('driving efficiency, scalability, and innovation') with concrete facts.\n"
        f"4. §8 Dashes: {'Keep dashes sparse.' if allow_dashes else 'Do NOT use em dashes (—), en dashes (–), or spaced double hyphens (--).'}\n"
        "5. §12 Ban Stock AI Words: Never use delve, pivotal, crucial, bolstered, meticulously, seamless, robust (figurative), "
        "showcase, testament, underscore, landscape, vibrant, groundbreaking.\n"
        "6. §13 & §15 Cut Shallow -ing Riders: Remove trailing participial fluff like ', ensuring...', ', highlighting...', "
        "', underscoring...', ', fostering...', ', contributing to...'. End on the concrete fact or metric.\n"
        "7. §19 No Bold Labels: Never prefix bullets with '**Topic:**'.\n"
        "8. HARD CONSTRAINT: Keep every number, metric, tool name, and target ATS keyword from `extracted_keywords` intact.\n"
        "Return strict JSON with the exact same schema as the input (`extracted_keywords`, `skills`, `roles`)."
    )
    pass2_user = json.dumps({"voice_profile": voice_profile, "draft_to_humanize": draft}, indent=2)
    humanized = call_llm_json(
        pass2_system,
        pass2_user,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.2,
    )

    draft_roles = draft.get("roles") or []
    custom_bullets_report: list[dict[str, Any]] = []
    cleaned_roles: list[dict[str, Any]] = []
    for r_idx, role in enumerate(humanized.get("roles") or []):
        if not isinstance(role, dict):
            continue
        draft_role = _match_draft_role(role, draft_roles, r_idx)
        draft_bullets = draft_role.get("bullets") or []
        cleaned_bullets: list[dict[str, Any]] = []
        for b_idx, b in enumerate(role.get("bullets") or []):
            fallback = _match_draft_bullet(
                b.get("text", "") if isinstance(b, dict) else b, draft_bullets, b_idx
            )
            if not isinstance(b, dict):
                b_obj = {
                    "text": b,
                    "is_custom": bool(fallback.get("is_custom", False)),
                    "matched_keywords": fallback.get("matched_keywords") or [],
                }
            else:
                b_obj = dict(b)
                if "is_custom" not in b_obj:
                    b_obj["is_custom"] = bool(fallback.get("is_custom", False))
                if not b_obj.get("matched_keywords") and fallback.get("matched_keywords"):
                    b_obj["matched_keywords"] = fallback["matched_keywords"]

            b_obj["text"] = humanize_text_deterministic(
                str(b_obj.get("text", "")), allow_dashes=allow_dashes
            )
            if not b_obj["text"]:
                continue  # cleanup can empty a bullet; never render a blank line
            cleaned_bullets.append(b_obj)
            if b_obj.get("is_custom"):
                custom_bullets_report.append(
                    {
                        "company": role.get("company", ""),
                        "title": role.get("title", ""),
                        "text": b_obj["text"],
                        "matched_keywords": b_obj.get("matched_keywords") or [],
                    }
                )
        role["bullets"] = cleaned_bullets
        cleaned_roles.append(role)

    keywords = humanized.get("extracted_keywords") or draft.get("extracted_keywords") or []
    # Only keep skills the candidate declared or the JD named verbatim; the model may invent others.
    allowed = {str(s).strip().lower() for s in (profile.get("skills") or [])} | {
        str(k).strip().lower() for k in keywords
    }
    skills: list[str] = []
    seen_skills: set[str] = set()
    for s in humanized.get("skills") or profile.get("skills") or []:
        key = str(s).strip().lower()
        if key and key in allowed and key not in seen_skills:
            skills.append(str(s).strip())
            seen_skills.add(key)

    return {
        "basics": profile.get("basics") or {},
        "skills": skills or list(profile.get("skills") or []),
        "roles": cleaned_roles,
        "education": profile.get("education") or [],
        "certifications": profile.get("certifications") or [],
        "extracted_keywords": keywords,
        "custom_bullets_report": custom_bullets_report,
    }


def _xml_escape(text: str) -> str:
    clean = XML_CONTROL_CHARS_RE.sub("", str(text))
    return (
        clean.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _contact_parts(basics: dict[str, Any]) -> list[Any]:
    return [
        p
        for p in [basics.get("email"), basics.get("phone"), basics.get("location"), *(basics.get("links") or [])]
        if p
    ]


def write_ats_docx(resume: dict[str, Any], output_path: Path) -> None:
    """Write a clean, single-column, ATS-compatible .docx file using standard OpenXML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    basics = resume.get("basics") or {}

    def make_p(
        text: str,
        *,
        bold: bool = False,
        size_half_pts: int = 21,
        space_after: int = 80,
        space_before: int = 0,
        bottom_border: bool = False,
        indent_left: int = 0,
    ) -> str:
        rpr = [
            '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>',
            f'<w:sz w:val="{size_half_pts}"/><w:szCs w:val="{size_half_pts}"/>',
        ]
        if bold:
            rpr.append("<w:b/>")
        ppr = [f'<w:spacing w:before="{space_before}" w:after="{space_after}"/>']
        if bottom_border:
            ppr.append(
                '<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="444444"/></w:pBdr>'
            )
        if indent_left:
            ppr.append(f'<w:ind w:left="{indent_left}" w:hanging="180"/>')
        return (
            f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>"
            f"<w:r><w:rPr>{''.join(rpr)}</w:rPr>"
            f'<w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r></w:p>'
        )

    name = str(basics.get("name") or "Candidate Name")
    paragraphs = [make_p(name, bold=True, size_half_pts=32, space_after=40)]

    contact_line = " | ".join(str(x) for x in _contact_parts(basics))
    if contact_line:
        paragraphs.append(make_p(contact_line, size_half_pts=20, space_after=140))

    if resume.get("roles"):
        paragraphs.append(
            make_p("WORK EXPERIENCE", bold=True, size_half_pts=22, space_before=120, space_after=60, bottom_border=True)
        )
        for role in resume["roles"]:
            if not isinstance(role, dict):
                continue
            header_parts = [p for p in [role.get("title"), role.get("company")] if p]
            meta_parts = [p for p in [role.get("location"), role.get("dates")] if p]
            role_line = " | ".join(str(p) for p in header_parts)
            if meta_parts:
                role_line += f" ({', '.join(str(p) for p in meta_parts)})"
            paragraphs.append(make_p(role_line, bold=True, size_half_pts=22, space_before=80, space_after=40))
            for b in role.get("bullets") or []:
                b_text = str(b["text"] if isinstance(b, dict) else b)
                paragraphs.append(make_p(f"• {b_text}", size_half_pts=21, space_after=40, indent_left=360))

    if resume.get("certifications"):
        paragraphs.append(
            make_p("CERTIFICATIONS", bold=True, size_half_pts=22, space_before=120, space_after=60, bottom_border=True)
        )
        cert_line = " • ".join(str(c) for c in resume["certifications"] if c)
        paragraphs.append(make_p(cert_line, size_half_pts=21, space_after=120))

    if resume.get("education"):
        paragraphs.append(
            make_p("EDUCATION", bold=True, size_half_pts=22, space_before=120, space_after=60, bottom_border=True)
        )
        for e in resume["education"]:
            edu_line = (
                " | ".join(str(x) for x in [e.get("degree"), e.get("school"), e.get("dates")] if x)
                if isinstance(e, dict)
                else str(e)
            )
            if edu_line:
                paragraphs.append(make_p(edu_line, size_half_pts=21, space_after=60))

    if resume.get("skills"):
        paragraphs.append(
            make_p("SKILLS", bold=True, size_half_pts=22, space_before=120, space_after=60, bottom_border=True)
        )
        skills_line = " • ".join(str(s) for s in resume["skills"] if s)
        paragraphs.append(make_p(skills_line, size_half_pts=21, space_after=120))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paragraphs)}"
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="864" w:right="864" w:bottom="864" w:left="864"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)


def _pdf_escape(text: str) -> str:
    text = re.sub(r"[\r\n\t]+", " ", XML_CONTROL_CHARS_RE.sub("", str(text)))
    replacements = {
        "—": ", ",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # In cp1252/WinAnsiEncoding, U+2022 ('•') encodes directly to byte 0x95
    text = text.encode("cp1252", errors="replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_text_width(text: str, font_size: float, bold: bool = False) -> float:
    """Estimate Helvetica string width in PDF points for centering, right-aligning, and wrapping."""
    w = 0.0
    for ch in text:
        if ch in "ilI.,:;|!' ":
            w += 0.25
        elif ch in "ftj()[]/-":
            w += 0.31
        elif ch in "mwMW@%":
            w += 0.78
        elif ch.isupper():
            w += 0.62
        elif ch in "0123456789":
            w += 0.56
        else:
            w += 0.50
    return w * font_size * (1.05 if bold else 1.0)


def _pdf_wrap(text: str, max_width_pt: float, font_size: float, bold: bool = False) -> list[str]:
    """Wrap text by rendered point width instead of fixed character count."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for word in words[1:]:
        candidate = f"{cur} {word}"
        if _pdf_text_width(candidate, font_size, bold=bold) <= max_width_pt:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)

    # A single long token (URL, ID) has no space to break on; split it by width instead.
    out: list[str] = []
    for line in lines:
        while _pdf_text_width(line, font_size, bold=bold) > max_width_pt and len(line) > 1:
            cut = len(line) - 1
            while cut > 1 and _pdf_text_width(line[:cut], font_size, bold=bold) > max_width_pt:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
        out.append(line)
    return out


def _pdf_has_unsupported_chars(text: str) -> bool:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return True
    return False


def write_ats_pdf(resume: dict[str, Any], output_path: Path) -> None:
    """
    Write a polished, ATS-accessible single-column PDF 1.4 document using Type1 Helvetica
    (Regular / Bold / Oblique), accent rules, right-aligned dates, and true hanging bullet indents.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if _pdf_has_unsupported_chars(json.dumps(resume, ensure_ascii=False, default=str)):
        print(
            "Warning: PDF font cannot show some characters; they will render as '?'. Use the .docx for those.",
            file=sys.stderr,
        )
    basics = resume.get("basics") or {}
    page_w, margin_l, margin_r = 612.0, 42.0, 42.0
    content_w = page_w - margin_l - margin_r
    right_x = page_w - margin_r
    top_y, bottom_y = 756.0, 36.0

    # We store draw items as (leading, draw_fn(y) -> list[str], keep_with_next_pts)
    items: list[tuple[float, Any, float]] = []

    def add_item(leading: float, draw_fn: Any, keep_next: float = 0.0) -> None:
        items.append((leading, draw_fn, keep_next))

    def add_spacer(pts: float) -> None:
        add_item(pts, lambda _y: [])

    def add_section_header(title: str) -> None:
        add_spacer(6.0)

        def _draw(y: float) -> list[str]:
            return [
                "0.11 0.20 0.36 rg",
                f"BT /F2 10.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(title)}) Tj ET",
                "0.72 0.77 0.84 RG 0.75 w",
                f"{margin_l:.1f} {y - 3.0:.1f} m {right_x:.1f} {y - 3.0:.1f} l S",
                "0 0 0 rg",
            ]

        add_item(15.0, _draw, keep_next=28.0)

    # 1. Centered Header Block (Name + Contact subtitle + Accent line)
    name = str(basics.get("name") or "Candidate Name")
    name_w = _pdf_text_width(name, 20.0, bold=True)
    name_x = max(margin_l, (page_w - name_w) / 2.0)
    add_item(
        22.0,
        lambda y, nx=name_x, nm=name: [
            "0.09 0.15 0.26 rg",
            f"BT /F2 20 Tf {nx:.1f} {y:.1f} Td ({_pdf_escape(nm)}) Tj ET",
            "0 0 0 rg",
        ],
    )

    contact_line = "  |  ".join(str(x) for x in _contact_parts(basics))
    if contact_line:
        for cline in _pdf_wrap(contact_line, content_w, 9.5):
            cw = _pdf_text_width(cline, 9.5)
            cx = max(margin_l, (page_w - cw) / 2.0)
            add_item(
                13.0,
                lambda y, x=cx, t=cline: [
                    "0.30 0.35 0.42 rg",
                    f"BT /F1 9.5 Tf {x:.1f} {y:.1f} Td ({_pdf_escape(t)}) Tj ET",
                    "0 0 0 rg",
                ],
            )

    add_item(
        8.0,
        lambda y: [
            "0.11 0.20 0.36 RG 1.2 w",
            f"{margin_l:.1f} {y + 2.0:.1f} m {right_x:.1f} {y + 2.0:.1f} l S",
        ],
    )

    # 2. Work Experience
    roles = resume.get("roles") or []
    if roles:
        add_section_header("WORK EXPERIENCE")
        for role in roles:
            if not isinstance(role, dict):
                continue
            title = str(role.get("title") or "").strip()
            company = str(role.get("company") or "").strip()
            location = str(role.get("location") or "").strip()
            dates = str(role.get("dates") or "").strip()

            left_main = " | ".join(p for p in (title, company) if p)
            left_loc = f"  ({location})" if location else ""
            date_w = _pdf_text_width(dates, 9.5) if dates else 0.0
            date_x = right_x - date_w
            left_total_w = _pdf_text_width(left_main, 10.2, bold=True) + _pdf_text_width(left_loc, 9.5)
            fits_single_line = (not dates) or (margin_l + left_total_w <= date_x - 10.0)

            if fits_single_line:
                def _draw_role_hdr(
                    y: float,
                    lm: str = left_main,
                    ll: str = left_loc,
                    dt: str = dates,
                    dx: float = date_x,
                ) -> list[str]:
                    loc_tj = (
                        f" 0.28 0.33 0.40 rg /F1 9.5 Tf ({_pdf_escape(ll)}) Tj"
                        if ll
                        else ""
                    )
                    ops = [
                        f"BT 0.08 0.10 0.14 rg /F2 10.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(lm)}) Tj{loc_tj} ET"
                    ]
                    if dt:
                        ops.append(
                            f"0.28 0.33 0.40 rg BT /F3 9.5 Tf {dx:.1f} {y:.1f} Td ({_pdf_escape(dt)}) Tj ET"
                        )
                    ops.append("0 0 0 rg")
                    return ops

                add_item(13.5, _draw_role_hdr, keep_next=14.0)
            else:
                add_item(
                    13.5,
                    lambda y, lm=left_main: [
                        f"0.08 0.10 0.14 rg BT /F2 10.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(lm)}) Tj ET 0 0 0 rg"
                    ],
                    keep_next=24.0,
                )
                sub_loc = location
                add_item(
                    11.5,
                    lambda y, sl=sub_loc, dt=dates, dx=date_x: [
                        *(
                            [f"0.28 0.33 0.40 rg BT /F1 9.3 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(sl)}) Tj ET"]
                            if sl
                            else []
                        ),
                        *(
                            [f"0.28 0.33 0.40 rg BT /F3 9.5 Tf {dx:.1f} {y:.1f} Td ({_pdf_escape(dt)}) Tj ET"]
                            if dt
                            else []
                        ),
                        "0 0 0 rg",
                    ],
                    keep_next=14.0,
                )

            bullet_x = margin_l + 6.0
            text_x = margin_l + 16.0
            bullet_wrap_w = right_x - text_x
            for b in role.get("bullets") or []:
                b_text = str(b["text"] if isinstance(b, dict) else b)
                wrapped = _pdf_wrap(b_text, bullet_wrap_w, 9.3)
                for idx, bline in enumerate(wrapped):
                    is_first = idx == 0

                    def _draw_bullet(
                        y: float, line_str: str = bline, first: bool = is_first
                    ) -> list[str]:
                        ops: list[str] = []
                        if first:
                            ops.append(
                                f"0.11 0.20 0.36 rg BT /F1 9.3 Tf {bullet_x:.1f} {y:.1f} Td (\x95) Tj ET 0.12 0.14 0.17 rg"
                            )
                        else:
                            ops.append("0.12 0.14 0.17 rg")
                        ops.append(
                            f"BT /F1 9.3 Tf {text_x:.1f} {y:.1f} Td ({_pdf_escape(line_str)}) Tj ET 0 0 0 rg"
                        )
                        return ops

                    add_item(11.6, _draw_bullet)
            add_spacer(2.5)

    # 3. Certifications
    certs = resume.get("certifications") or []
    if certs:
        add_section_header("CERTIFICATIONS")
        certs_str = "  •  ".join(str(c) for c in certs if c)
        for cline in _pdf_wrap(certs_str, content_w, 9.2):
            add_item(
                11.5,
                lambda y, cl=cline: [
                    f"0.12 0.14 0.17 rg BT /F1 9.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(cl)}) Tj ET 0 0 0 rg"
                ],
            )

    # 4. Education
    education = resume.get("education") or []
    if education:
        add_section_header("EDUCATION")
        for edu in education:
            if not isinstance(edu, dict):
                edu = {"degree": str(edu)}
            school = str(edu.get("school") or "").strip()
            degree = str(edu.get("degree") or "").strip()
            edates = str(edu.get("dates") or "").strip()
            edate_w = _pdf_text_width(edates, 9.5) if edates else 0.0
            edate_x = right_x - edate_w

            def _draw_edu_school(
                y: float, sc: str = school, dt: str = edates, dx: float = edate_x
            ) -> list[str]:
                ops = [
                    f"0.08 0.10 0.14 rg BT /F2 10.0 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(sc)}) Tj ET"
                ]
                if dt:
                    ops.append(
                        f"0.28 0.33 0.40 rg BT /F2 9.5 Tf {dx:.1f} {y:.1f} Td ({_pdf_escape(dt)}) Tj ET"
                    )
                ops.append("0 0 0 rg")
                return ops

            if school:
                add_item(12.5, _draw_edu_school, keep_next=12.0 if degree else 0.0)
            if degree:
                for dline in _pdf_wrap(degree, content_w, 9.2):
                    add_item(
                        11.5,
                        lambda y, dl=dline: [
                            f"0.20 0.23 0.28 rg BT /F3 9.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(dl)}) Tj ET 0 0 0 rg"
                        ],
                    )
            add_spacer(2.0)

    # 5. Skills (at the very bottom)
    skills = resume.get("skills") or []
    if skills:
        add_section_header("SKILLS")
        skills_str = "  •  ".join(str(s) for s in skills if s)
        for sline in _pdf_wrap(skills_str, content_w, 9.2):
            add_item(
                11.5,
                lambda y, sl=sline: [
                    f"0.12 0.14 0.17 rg BT /F1 9.2 Tf {margin_l:.1f} {y:.1f} Td ({_pdf_escape(sl)}) Tj ET 0 0 0 rg"
                ],
            )

    # Paginate items
    pages_streams: list[bytes] = []
    cur_ops: list[str] = []
    y = top_y
    for leading, draw_fn, keep_next in items:
        if y - leading - keep_next < bottom_y:
            pages_streams.append("\n".join(cur_ops).encode("latin-1"))
            cur_ops = []
            y = top_y
        y -= leading
        cur_ops.extend(draw_fn(y))
    if cur_ops or not pages_streams:
        pages_streams.append("\n".join(cur_ops).encode("latin-1"))

    # Objects: 1=Catalog, 2=Pages, 3=Helvetica, 4=Helvetica-Bold, 5=Helvetica-Oblique
    objects: list[bytes] = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>",
    ]
    page_obj_ids: list[int] = []
    for stream in pages_streams:
        content_id = len(objects) + 1
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        page_id = len(objects) + 1
        page_obj_ids.append(page_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("latin-1")
        )

    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_obj_ids)} >>".encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for idx, obj_body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("latin-1") + obj_body + b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    )
    output_path.write_bytes(bytes(out))


def _positive_int(value: str) -> int:
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or greater, got {count}")
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume_gen.py",
        description="ATS-beating resume matcher, custom experience generator, and humanizer.",
    )
    parser.add_argument(
        "--api-key",
        default=(
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENCODE_API_KEY")
            or ""
        ),
        help="API key (defaults to OPENAI_API_KEY, OPENROUTER_API_KEY, or OPENCODE_API_KEY env var).",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "API base URL or shorthand ('opencode-go', 'opencode', 'openrouter', or any OpenAI-compatible URL; "
            "defaults to OPENAI_BASE_URL / OPENROUTER_BASE_URL / OPENCODE_BASE_URL)."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model ID to use (defaults to OPENAI_MODEL or gpt-4o).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest",
        help="Parse sample resumes (.pdf, .docx, .txt, .md) into a human-editable YAML experience library.",
    )
    p_ingest.add_argument("resumes", nargs="+", type=Path, help="Paths to one or more sample resume files.")
    p_ingest.add_argument(
        "-o", "--output", type=Path, default=Path("profile.yaml"), help="Output YAML profile path (default: profile.yaml)."
    )

    p_tailor = sub.add_parser(
        "tailor",
        help="Match profile.yaml to a job description, draft N custom bullets (default 3), humanize, and export .docx + .pdf.",
    )
    p_tailor.add_argument("-p", "--profile", type=Path, default=Path("profile.yaml"), help="Path to profile.yaml.")
    p_tailor.add_argument("-j", "--jd", type=Path, required=True, help="Path to target job description file.")
    p_tailor.add_argument("-o", "--outdir", type=Path, default=Path("output"), help="Output directory (default: output/).")
    p_tailor.add_argument("--name-prefix", default="tailored_resume", help="Filename prefix (default: tailored_resume).")
    p_tailor.add_argument(
        "--custom-bullets",
        type=_positive_int,
        default=3,
        help="Number of fully custom JD-matched bullets to insert into existing roles (default: 3).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ingest":
        profile = ingest_resumes(
            args.resumes,
            args.output,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
        )
        role_count = len(profile.get("roles") or [])
        bullet_count = sum(len(r.get("bullets") or []) for r in (profile.get("roles") or []))
        print(f"Saved experience library to {args.output} ({role_count} roles, {bullet_count} bullets).")
        return 0

    if args.command == "tailor":
        if not args.profile.exists():
            raise FileNotFoundError(
                f"Profile file '{args.profile}' not found. Run `ingest` first or create it."
            )
        profile = yaml.safe_load(args.profile.read_text(encoding="utf-8")) or {}
        jd_text = extract_text_from_file(args.jd)
        if not jd_text.strip():
            raise ValueError(
                f"Job description '{args.jd}' contains no readable text (a scanned PDF needs OCR first)."
            )
        tailored = tailor_resume(
            profile,
            jd_text,
            custom_bullet_count=args.custom_bullets,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
        )
        safe_prefix = Path(args.name_prefix).name or "tailored_resume"
        args.outdir.mkdir(parents=True, exist_ok=True)
        docx_path = args.outdir / f"{safe_prefix}.docx"
        pdf_path = args.outdir / f"{safe_prefix}.pdf"
        report_path = args.outdir / f"{safe_prefix}_report.json"
        tmps = [p.with_name(p.name + ".tmp") for p in (docx_path, pdf_path, report_path)]

        # Render everything before replacing the previous run's files, so a failure can't mix old and new.
        try:
            write_ats_docx(tailored, tmps[0])
            write_ats_pdf(tailored, tmps[1])
            # default=str: profile.yaml may contain unquoted dates, which are not JSON serializable
            tmps[2].write_text(json.dumps(tailored, indent=2, default=str), encoding="utf-8")
            for tmp, final in zip(tmps, (docx_path, pdf_path, report_path)):
                os.replace(tmp, final)
        finally:
            for tmp in tmps:
                tmp.unlink(missing_ok=True)

        inserted = len(tailored["custom_bullets_report"])
        if inserted != args.custom_bullets:
            print(
                f"Warning: requested {args.custom_bullets} custom bullets, model returned {inserted}.",
                file=sys.stderr,
            )

        print(f"Generated ATS DOCX: {docx_path}")
        print(f"Generated ATS PDF:  {pdf_path}")
        print(f"Matched Keywords ({len(tailored['extracted_keywords'])}): {', '.join(map(str, tailored['extracted_keywords']))}")
        print(f"Inserted Custom Experience Bullets ({inserted}):")
        for idx, cb in enumerate(tailored["custom_bullets_report"], start=1):
            print(f"  {idx}. [{cb['title']} @ {cb['company']}] {cb['text']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
