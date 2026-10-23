#!/usr/bin/env python3
"""Self-check test suite for resume_gen.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

import resume_gen


def test_humanizer_deterministic() -> None:
    raw = (
        "**Performance:** Meticulously spearheaded the migration — not only reducing latency by 42.5%, "
        "but also adding --dry-run CLI support, ensuring 99.9% availability across the evolving landscape. "
        "Meticulously scaled Kafka clusters across 3 regions."
    )
    cleaned = resume_gen.humanize_text_deterministic(raw, allow_dashes=False)
    assert "**" not in cleaned, f"Bold label remained: {cleaned}"
    assert "—" not in cleaned, f"Em dash remained: {cleaned}"
    assert "meticulously" not in cleaned.lower(), f"AI buzzword remained: {cleaned}"
    assert "ensuring" not in cleaned.lower(), f"Shallow -ing rider remained: {cleaned}"
    assert ".9%" not in cleaned, f"Decimal number in rider left fragment: {cleaned}"
    assert "not only" not in cleaned.lower(), f"Not-only contrast remained: {cleaned}"
    assert "42.5%" in cleaned, f"Metric lost: {cleaned}"
    assert "--dry-run" in cleaned, f"Unspaced CLI flag corrupted: {cleaned}"
    assert ". Scaled Kafka" in cleaned, f"Second sentence not capitalized: {cleaned}"


def test_custom_bullets_cli_arg() -> None:
    parser = resume_gen.build_parser()
    for count in ("1", "2", "5", "10"):
        args = parser.parse_args(["tailor", "-j", "jd.txt", "--custom-bullets", count])
        assert args.custom_bullets == int(count)
    assert parser.parse_args(["tailor", "-j", "jd.txt"]).custom_bullets == 3
    for bad in ("0", "-1"):
        try:
            parser.parse_args(["tailor", "-j", "jd.txt", "--custom-bullets", bad])
        except SystemExit:
            continue
        raise AssertionError(f"--custom-bullets {bad} should be rejected")


def test_merge_extras_and_shape_guards() -> None:
    # Extra fields on a role survive a re-ingest
    merged = resume_gen.merge_profiles(
        {"roles": [{"company": "Acme", "title": "Eng", "notes": "KEEP ME", "bullets": ["x"]}]},
        {"roles": [{"company": "Acme", "title": "Eng", "bullets": ["y"]}]},
    )
    assert merged["roles"][0]["notes"] == "KEEP ME"
    assert merged["roles"][0]["bullets"] == ["x", "y"]

    # Reworded duplicate is skipped, a genuinely different metric is kept
    dup = resume_gen.merge_profiles(
        {"roles": [{"company": "C", "title": "T", "bullets": ["Cut Snowflake spend by 28%."]}]},
        {"roles": [{"company": "C", "title": "T", "bullets": ["Cut spend by 28% in Snowflake."]}]},
    )
    assert dup["roles"][0]["bullets"] == ["Cut Snowflake spend by 28%."]
    distinct = resume_gen.merge_profiles(
        {"roles": [{"company": "C", "title": "T", "bullets": ["Cut spend by 28%."]}]},
        {"roles": [{"company": "C", "title": "T", "bullets": ["Cut spend by 20%."]}]},
    )
    assert len(distinct["roles"][0]["bullets"]) == 2

    # Model returns a role as a plain string: skip it instead of crashing
    bad = {"extracted_keywords": ["Python"], "skills": ["Python"], "roles": ["Acme Corp - Senior Engineer"]}
    with patch("resume_gen.call_llm_json", side_effect=[bad, bad]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", api_key="k")
    assert out["roles"] == []

    # is_custom follows the bullet text, not its position, when the humanizer reorders bullets
    draft = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": [
                    {"text": "Alpha beta gamma delta", "is_custom": True},
                    {"text": "One two three four", "is_custom": False},
                ],
            }
        ],
    }
    reordered = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": ["One two three four", "Alpha beta gamma delta"],
            }
        ],
    }
    with patch("resume_gen.call_llm_json", side_effect=[draft, reordered]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", api_key="k")
    assert [c["text"] for c in out["custom_bullets_report"]] == ["Alpha beta gamma delta."]


def test_custom_bullet_count_warns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        profile_path = tmpdir / "profile.yaml"
        profile_path.write_text("skills: [Python]\nroles: []\n", encoding="utf-8")
        jd_path = tmpdir / "jd.txt"
        jd_path.write_text("Python role", encoding="utf-8")
        one_bullet = {
            "extracted_keywords": ["Python"],
            "skills": ["Python"],
            "roles": [
                {
                    "company": "C",
                    "title": "T",
                    "bullets": [{"text": "Did X.", "is_custom": True}],
                }
            ],
        }
        err = io.StringIO()
        with patch("resume_gen.call_llm_json", side_effect=[one_bullet, one_bullet]):
            with contextlib.redirect_stderr(err):
                code = resume_gen.main(
                    [
                        "--api-key",
                        "k",
                        "tailor",
                        "-p",
                        str(profile_path),
                        "-j",
                        str(jd_path),
                        "-o",
                        str(tmpdir / "out"),
                        "--custom-bullets",
                        "5",
                    ]
                )
        assert code == 0
        assert "requested 5 custom bullets, model returned 1" in err.getvalue()
        assert not list((tmpdir / "out").glob("*.tmp"))


def test_role_and_bullet_matching() -> None:
    # Pass 2 swaps two roles at the same company: bullets must follow company + title, not position
    draft = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "Acme",
                "title": "Senior Eng",
                "bullets": [
                    {"text": "Built the custom risk platform for auditors.", "is_custom": True},
                    {"text": "Ran weekly reviews.", "is_custom": False},
                ],
            },
            {"company": "Acme", "title": "Junior Eng", "bullets": [{"text": "Maintained test suites.", "is_custom": False}]},
        ],
    }
    humanized = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {"company": "Acme", "title": "Junior Eng", "bullets": ["Maintained test suites."]},
            {
                "company": "Acme",
                "title": "Senior Eng",
                "bullets": ["Built the custom risk platform for auditors.", "Ran weekly reviews."],
            },
        ],
    }
    with patch("resume_gen.call_llm_json", side_effect=[draft, humanized]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", api_key="k")
    assert [(c["title"], c["text"]) for c in out["custom_bullets_report"]] == [
        ("Senior Eng", "Built the custom risk platform for auditors.")
    ]

    # A rewritten non-custom bullet ties with a custom one: position must win the tie
    draft = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": [
                    {"text": "Reduced risk across vendor reviews", "is_custom": True},
                    {"text": "Reduced cost across vendor reviews", "is_custom": False},
                ],
            }
        ],
    }
    humanized = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": ["Reduced risk across vendor reviews", "Reduced spend across vendor reviews"],
            }
        ],
    }
    with patch("resume_gen.call_llm_json", side_effect=[draft, humanized]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", custom_bullet_count=1, api_key="k")
    assert [c["text"] for c in out["custom_bullets_report"]] == ["Reduced risk across vendor reviews."]


def test_dotenv_values_and_empty_jd() -> None:
    cases = {
        "PLAIN": "abc",
        "COMMENTED": "abc # prod",
        "QUOTED": '"a b" # c',
        "HASH_INSIDE": "'a # b'",
        "EQUALS": "a=b",
        "EMPTY": '""',
        "UNTERMINATED": '"unterminated',
        "BLANK_COMMENT": " # note",
    }
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / ".env"
        env_file.write_text(
            "\n".join(f"{k}={v}" for k, v in cases.items()), encoding="utf-8"
        )
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp)
            for k in cases:
                os.environ.pop(k, None)
            resume_gen._load_dotenv()
            assert os.environ["PLAIN"] == "abc"
            assert os.environ["COMMENTED"] == "abc"
            assert os.environ["QUOTED"] == "a b"
            assert os.environ["HASH_INSIDE"] == "a # b"
            assert os.environ["EQUALS"] == "a=b"
            assert os.environ["EMPTY"] == ""
            assert os.environ["UNTERMINATED"] == "unterminated"
            assert os.environ["BLANK_COMMENT"] == ""
        finally:
            os.chdir(old_cwd)
            for k in cases:
                os.environ.pop(k, None)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        profile_path = tmpdir / "profile.yaml"
        profile_path.write_text("skills: [Python]\nroles: []\n", encoding="utf-8")
        jd_path = tmpdir / "jd.txt"
        jd_path.write_text("  \n", encoding="utf-8")
        try:
            resume_gen.main(
                ["--api-key", "k", "tailor", "-p", str(profile_path), "-j", str(jd_path), "-o", str(tmpdir / "out")]
            )
        except ValueError as exc:
            assert "no readable text" in str(exc)
        else:
            raise AssertionError("empty JD should be rejected")
        assert not (tmpdir / "out").exists()


def test_payload_temperature_and_pdf_edges() -> None:
    for model, check in [
        ("kimi-k3", lambda p: p.get("temperature") == 0.7),
        ("gpt-6-luna", lambda p: p.get("temperature") == 0.7),
        ("claude-haiku-x", lambda p: p.get("temperature") == 0.7),
        ("gemini-x", lambda p: p.get("generationConfig", {}).get("temperature") == 0.7),
    ]:
        _, payload, _ = resume_gen._resolve_endpoint_and_payload("opencode-go", model, "s", "u", 0.7)
        assert check(payload), f"temperature missing for {model}: {payload}"

    long_token = "x" * 130
    lines = resume_gen._pdf_wrap(long_token, 512, 9.3)
    assert len(lines) > 1
    assert all(resume_gen._pdf_text_width(line, 9.3) <= 512 for line in lines)

    assert "e.g. vendor" in resume_gen.humanize_text_deterministic(
        "Automated reviews (e.g. vendor checks) for teams."
    )
    assert "28%. Scaled" in resume_gen.humanize_text_deterministic("Cut spend by 28%. Scaled the team.")

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "x.pdf"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            resume_gen.write_ats_pdf(
                {"basics": {"name": "张伟", "email": "z@example.com"}, "roles": []}, pdf_path
            )
        assert "cannot show some characters" in err.getvalue()
        assert pdf_path.stat().st_size > 0


def test_retry_serialization_and_empty_bullets() -> None:
    # A timeout is retried, not raised on the first attempt
    class Ok:
        def __enter__(self) -> "Ok":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()

    import socket

    with patch("urllib.request.urlopen", side_effect=[socket.timeout("slow"), Ok()]), patch("time.sleep"):
        assert resume_gen.call_llm_json("s", "u", api_key="k") == {"ok": True}

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Unquoted YAML date in education: it must be serializable into the report
        profile_path = tmpdir / "profile.yaml"
        profile_path.write_text(
            "basics: {name: Jane}\nskills: [Python]\nroles: []\n"
            "education:\n  - {school: UT, degree: BS, dates: 2020-01-01}\n",
            encoding="utf-8",
        )
        jd_path = tmpdir / "jd.txt"
        jd_path.write_text("Python", encoding="utf-8")
        response = {
            "extracted_keywords": [2024, "Python"],
            "skills": ["Python"],
            "roles": [
                {
                    "company": "C",
                    "title": "T",
                    "bullets": [
                        {"text": "**Label:**", "is_custom": True},
                        {"text": "Real bullet.", "is_custom": False},
                    ],
                }
            ],
        }
        outdir = tmpdir / "out"
        with patch("resume_gen.call_llm_json", side_effect=[response, response]):
            resume_gen.main(
                ["--api-key", "k", "tailor", "-p", str(profile_path), "-j", str(jd_path), "-o", str(outdir)]
            )

        report = json.loads((outdir / "tailored_resume_report.json").read_text(encoding="utf-8"))
        assert "2020-01-01" in json.dumps(report)
        # The label-only bullet is dropped instead of rendering a blank line
        assert [b["text"] for b in report["roles"][0]["bullets"]] == ["Real bullet."]
        assert report["custom_bullets_report"] == []

        # A failed render leaves the previous outputs untouched
        (outdir / "tailored_resume.docx").write_bytes(b"OLD DOCX")
        with patch("resume_gen.call_llm_json", side_effect=[response, response]), patch(
            "resume_gen.write_ats_pdf", side_effect=RuntimeError("boom")
        ):
            try:
                resume_gen.main(
                    ["--api-key", "k", "tailor", "-p", str(profile_path), "-j", str(jd_path), "-o", str(outdir)]
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected render failure")
        assert (outdir / "tailored_resume.docx").read_bytes() == b"OLD DOCX"
        assert not list(outdir.glob("*.tmp"))


def test_call_llm_json_and_bad_docx() -> None:
    class FakeResp:
        def __enter__(self) -> "FakeResp":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            body = {
                "choices": [
                    {"message": {"content": 'Here is your JSON:\n```json\n{"ok": true}\n```'}}
                ]
            }
            return json.dumps(body).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        res = resume_gen.call_llm_json("sys", "user", api_key="k")
        assert res == {"ok": True}

    # Verify OpenCode Go endpoint routing across all 4 API families
    u1, _, f1 = resume_gen._resolve_endpoint_and_payload("opencode-go", "kimi-k3", "s", "u", 0.2)
    assert u1 == "https://opencode.ai/inference/go/openai/v1/chat/completions" and f1 == "chat"
    u2, _, f2 = resume_gen._resolve_endpoint_and_payload("opencode-go", "gpt-6-luna", "s", "u", 0.2)
    assert u2 == "https://opencode.ai/inference/go/openai/v1/responses" and f2 == "responses"
    u3, _, f3 = resume_gen._resolve_endpoint_and_payload("opencode-go", "claude-haiku-5-5", "s", "u", 0.2)
    assert u3 == "https://opencode.ai/inference/go/anthropic/v1/messages" and f3 == "anthropic"
    u4, _, f4 = resume_gen._resolve_endpoint_and_payload("opencode-go", "gemini-4-argon-contributor", "s", "u", 0.2)
    assert "google/v1beta/models/gemini-4-argon-contributor:generateContent" in u4 and f4 == "gemini"

    # Verify standard OpenAI and OpenRouter routing (both explicit and sk-or- auto-detected)
    uo, po, fo = resume_gen._resolve_endpoint_and_payload(
        "https://api.openai.com/v1", "gpt-4o", "s", "u", 0.2, api_key="sk-proj-123"
    )
    assert uo == "https://api.openai.com/v1/chat/completions" and fo == "chat"
    assert po.get("response_format") == {"type": "json_object"}

    ur1, pr1, fr1 = resume_gen._resolve_endpoint_and_payload(
        "https://api.openai.com/v1", "anthropic/claude-3.5-sonnet", "s", "u", 0.2, api_key="sk-or-v1-abc"
    )
    assert ur1 == "https://openrouter.ai/api/v1/chat/completions" and fr1 == "chat"
    assert "response_format" not in pr1

    ur2, _, fr2 = resume_gen._resolve_endpoint_and_payload(
        "openrouter", "openai/gpt-4o", "s", "u", 0.2, api_key="any-key"
    )
    assert ur2 == "https://openrouter.ai/api/v1/chat/completions" and fr2 == "chat"

    with tempfile.TemporaryDirectory() as tmp:
        bad_docx = Path(tmp) / "bad.docx"
        bad_docx.write_bytes(b"not a zip file")
        try:
            resume_gen.extract_text_from_file(bad_docx)
            assert False, "Expected ValueError for corrupt .docx"
        except ValueError as exc:
            assert "bad.docx" in str(exc)

        # Verify .env loader reads key=value pairs without external dotenv dependency
        env_file = Path(tmp) / ".env"
        env_file.write_text('export TEST_RESUME_GEN_KEY="secret-from-dotenv"\n', encoding="utf-8")
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp)
            os.environ.pop("TEST_RESUME_GEN_KEY", None)
            resume_gen._load_dotenv()
            assert os.environ.get("TEST_RESUME_GEN_KEY") == "secret-from-dotenv"
        finally:
            os.chdir(old_cwd)
            os.environ.pop("TEST_RESUME_GEN_KEY", None)


def test_ingest_merge_and_tailor_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        sample_resume = tmpdir / "sample_resume.txt"
        sample_resume.write_text(
            "Jane Doe\njane@example.com | Austin, TX\n"
            "Senior Data Engineer at Acme Corp (2021 - Present)\n"
            "- Built Kafka streaming pipelines handling 50k events/sec.\n"
            "- Cut Snowflake warehouse spend by 28% by partitioning staging tables.\n",
            encoding="utf-8",
        )
        profile_path = tmpdir / "profile.yaml"

        mock_ingest_1 = {
            "basics": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-0100",
                "location": "Austin, TX",
                "links": ["linkedin.com/in/janedoe"],
            },
            "voice_profile": {"tone": "Direct past-tense, metric-first, no fluff"},
            "skills": ["Python", "SQL", "Kafka", "Snowflake"],
            "certifications": ["AWS Certified Security - Specialty"],
            "roles": [
                {
                    "company": "Acme Corp",
                    "title": "Senior Data Engineer",
                    "location": "Austin, TX",
                    "dates": "2021 - Present",
                    "bullets": [
                        "Built Kafka streaming pipelines handling 50k events/sec.",
                        "Cut Snowflake warehouse spend by 28% by partitioning staging tables.",
                    ],
                }
            ],
            "education": [
                {"school": "UT Austin", "degree": "B.S. Computer Science", "dates": "2017 - 2021"}
            ],
        }

        with patch("resume_gen.call_llm_json", return_value=mock_ingest_1):
            resume_gen.main(
                ["--api-key", "test-key", "ingest", str(sample_resume), "-o", str(profile_path)]
            )

        # Simulate manual user edit to voice_profile in profile.yaml
        edited_profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        edited_profile["voice_profile"]["uses_dashes"] = True
        profile_path.write_text(yaml.safe_dump(edited_profile, sort_keys=False), encoding="utf-8")

        # Second ingest merges new bullet and link without clobbering user's uses_dashes edit
        mock_ingest_2 = {
            "basics": {"name": "Jane Doe", "links": ["github.com/janedoe"]},
            "voice_profile": {"tone": "Overwritten tone attempt"},
            "skills": ["Kafka", "dbt"],
            "roles": [
                {
                    "company": "Acme Corp",
                    "title": "Senior Data Engineer",
                    "bullets": [
                        "Built Kafka streaming pipelines handling 50k events/sec.",
                        "Reduced backfill runtime by 60% using incremental tables and partitioned staging.",
                    ],
                }
            ],
            "education": [],
        }
        with patch("resume_gen.call_llm_json", return_value=mock_ingest_2):
            resume_gen.main(
                ["--api-key", "test-key", "ingest", str(sample_resume), "-o", str(profile_path)]
            )

        merged = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        assert merged["voice_profile"]["uses_dashes"] is True
        assert merged["voice_profile"]["tone"] == "Direct past-tense, metric-first, no fluff"
        assert merged["basics"]["links"] == ["linkedin.com/in/janedoe", "github.com/janedoe"]
        assert "summary" not in merged
        assert len(merged["roles"][0]["bullets"]) == 3

        # Reset uses_dashes to False for tailor test
        merged["voice_profile"]["uses_dashes"] = False
        profile_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")

        jd_path = tmpdir / "jd.txt"
        jd_path.write_text(
            "Looking for a Staff Data Engineer with Python, dbt, Airflow, Dagster, and Snowflake experience.",
            encoding="utf-8",
        )
        outdir = tmpdir / "out"

        pass1_draft = {
            "extracted_keywords": ["Python", "dbt", "Airflow", "Dagster", "Snowflake"],
            "skills": ["Python", "Snowflake", "dbt", "Airflow", "Dagster", "Kafka", "SQL"],
            "roles": [
                {
                    "company": "Acme Corp",
                    "title": "Senior Data Engineer",
                    "location": "Austin, TX",
                    "dates": "2021 - Present",
                    "bullets": [
                        {
                            "text": "Built Kafka\x0c and Python streaming pipelines handling 50k events/sec.",
                            "is_custom": False,
                            "matched_keywords": ["Python", "Kafka"],
                        },
                        {
                            "text": "**Orchestration:** Meticulously migrated 40+ Airflow DAGs to Dagster — ensuring 99.9% reliability.",
                            "is_custom": True,
                            "matched_keywords": ["Airflow", "Dagster"],
                        },
                        {
                            "text": "Designed modular dbt core models for finance reporting, cutting nightly runtimes by 35%.",
                            "is_custom": True,
                            "matched_keywords": ["dbt"],
                        },
                        {
                            "text": "Implemented automated data quality tests across Snowflake marts using Python and dbt.",
                            "is_custom": True,
                            "matched_keywords": ["Snowflake", "Python", "dbt"],
                        },
                    ],
                }
            ],
        }
        # Pass 2 returns plain strings for bullets to verify fallback preservation of is_custom
        pass2_humanized = {
            "extracted_keywords": pass1_draft["extracted_keywords"],
            # "Kubernetes" is invented: in neither profile.skills nor extracted_keywords
            "skills": pass1_draft["skills"] + ["Kubernetes"],
            "roles": [
                {
                    "company": "Acme Corp",
                    "title": "Senior Data Engineer",
                    "location": "Austin, TX",
                    "dates": "2021 - Present",
                    "bullets": [b["text"] for b in pass1_draft["roles"][0]["bullets"]],
                }
            ],
        }

        with patch("resume_gen.call_llm_json", side_effect=[pass1_draft, pass2_humanized]):
            resume_gen.main(
                [
                    "--api-key",
                    "test-key",
                    "tailor",
                    "-p",
                    str(profile_path),
                    "-j",
                    str(jd_path),
                    "-o",
                    str(outdir),
                    "--custom-bullets",
                    "3",
                ]
            )

        docx_file = outdir / "tailored_resume.docx"
        pdf_file = outdir / "tailored_resume.pdf"
        report_file = outdir / "tailored_resume_report.json"

        docx_text = resume_gen.extract_text_from_file(docx_file)
        assert "Jane Doe" in docx_text
        assert "Dagster" in docx_text
        assert "**Orchestration:**" not in docx_text
        assert "ensuring 99.9%" not in docx_text
        assert ".9%" not in docx_text
        assert "SKILLS" in docx_text
        assert "CERTIFICATIONS" in docx_text
        assert "AWS Certified Security - Specialty" in docx_text

        pdf_text = resume_gen.extract_text_from_file(pdf_file)
        assert "Jane Doe" in pdf_text
        assert "WORK EXPERIENCE" in pdf_text
        assert "Dagster" in pdf_text
        assert "CERTIFICATIONS" in pdf_text
        assert "AWS Certified Security - Specialty" in pdf_text

        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert len(report["custom_bullets_report"]) == 3

        # Skills may only come from profile.skills or extracted_keywords
        assert "Kubernetes" not in report["skills"]
        assert "Dagster" in report["skills"]
        assert "SQL" in report["skills"]
        assert "Kubernetes" not in docx_text and "Kubernetes" not in pdf_text

        # Verify multi-page PDF pagination
        big_resume = dict(report)
        big_resume["roles"] = [
            {
                "company": "BigCorp",
                "title": "Principal Engineer",
                "location": "Remote",
                "dates": "2015 - 2026",
                "bullets": [f"Delivered system improvement #{i} reducing cost by {i}%." for i in range(1, 65)],
            }
        ]
        multipage_pdf = outdir / "multipage.pdf"
        resume_gen.write_ats_pdf(big_resume, multipage_pdf)
        mp_text = resume_gen.extract_text_from_file(multipage_pdf)
        assert "improvement #1 " in mp_text
        assert "improvement #64 " in mp_text


if __name__ == "__main__":
    test_humanizer_deterministic()
    test_custom_bullets_cli_arg()
    test_merge_extras_and_shape_guards()
    test_custom_bullet_count_warns()
    test_dotenv_values_and_empty_jd()
    test_payload_temperature_and_pdf_edges()
    test_role_and_bullet_matching()
    test_retry_serialization_and_empty_bullets()
    test_call_llm_json_and_bad_docx()
    test_ingest_merge_and_tailor_pipeline()
    print("ALL TESTS PASSED")
