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
    assert "ensuring 99.9% availability" in cleaned, f"Meaningful outcome lost: {cleaned}"
    assert "not only" not in cleaned.lower(), f"Not-only contrast remained: {cleaned}"
    assert "42.5%" in cleaned, f"Metric lost: {cleaned}"
    assert "--dry-run" in cleaned, f"Unspaced CLI flag corrupted: {cleaned}"
    assert "3 regions" in cleaned, f"Scope lost: {cleaned}"


def test_custom_bullets_cli_arg() -> None:
    parser = resume_gen.build_parser()
    for count in ("0", "1", "2", "5", "10"):
        args = parser.parse_args(["tailor", "-j", "jd.txt", "--custom-bullets", count])
        assert args.custom_bullets == int(count)
    assert parser.parse_args(["tailor", "-j", "jd.txt"]).custom_bullets == 3
    for bad in ("-1", "bad"):
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


def test_custom_bullets_restored_when_humanizer_drops_them() -> None:
    # The humanizer pass drops the custom bullet entirely: the draft must still carry it.
    draft = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": [
                    {"text": "Automated evidence collection for SOC 2 audits", "is_custom": True},
                    {"text": "Ran weekly reviews", "is_custom": False},
                ],
            }
        ],
    }
    dropped = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [{"company": "C", "title": "T", "bullets": ["Ran weekly reviews"]}],
    }
    with patch("resume_gen.call_llm_json", side_effect=[draft, dropped]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", api_key="k")
    assert [b["text"] for b in out["roles"][0]["bullets"]] == [
        "Automated evidence collection for SOC 2 audits.",
        "Ran weekly reviews.",
    ]
    assert [c["text"] for c in out["custom_bullets_report"]] == [
        "Automated evidence collection for SOC 2 audits."
    ]

    # The custom bullet survives as a rewrite but loses its flag: claim it, never duplicate it.
    unflagged = {
        "extracted_keywords": ["Python"],
        "skills": ["Python"],
        "roles": [
            {
                "company": "C",
                "title": "T",
                "bullets": [
                    {"text": "Ran weekly reviews", "is_custom": False},
                    {"text": "Automated SOC 2 audit evidence collection", "is_custom": False},
                ],
            }
        ],
    }
    with patch("resume_gen.call_llm_json", side_effect=[draft, unflagged]):
        out = resume_gen.tailor_resume({"skills": ["Python"], "roles": []}, "jd", api_key="k")
    assert [b["text"] for b in out["roles"][0]["bullets"]] == [
        "Automated SOC 2 audit evidence collection.",
        "Ran weekly reviews.",
    ]
    assert [c["text"] for c in out["custom_bullets_report"]] == [
        "Automated SOC 2 audit evidence collection."
    ]


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
        assert resume_gen.call_llm_json(
            "s", "u", api_key="k", base_url="https://api.openai.com/v1"
        ) == {"ok": True}

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
        res = resume_gen.call_llm_json("sys", "user", api_key="k", base_url="https://api.openai.com/v1")
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
        assert "ensuring 99.9%" in docx_text
        assert "SKILLS" in docx_text
        assert "CERTIFICATIONS" in docx_text
        assert "AWS Certified Security - Specialty" in docx_text
        assert docx_text.index("CERTIFICATIONS") < docx_text.index("WORK EXPERIENCE")

        pdf_text = resume_gen.extract_text_from_file(pdf_file)
        assert "Jane Doe" in pdf_text
        assert "WORK EXPERIENCE" in pdf_text
        assert "Dagster" in pdf_text
        assert "CERTIFICATIONS" in pdf_text
        assert "AWS Certified Security - Specialty" in pdf_text
        assert pdf_text.index("CERTIFICATIONS") < pdf_text.index("WORK EXPERIENCE")

        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert len(report["custom_bullets_report"]) == 3

        # The drafting pass selects skills; the style pass cannot add or reselect them.
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


def test_codex_backend() -> None:
    import subprocess

    invocations = []

    def fake_run(command, **kwargs):
        invocations.append((command, kwargs))
        output = Path(command[command.index("--output-last-message") + 1])
        assert output.parent == Path(kwargs["cwd"])
        assert Path(kwargs["cwd"]) != Path.cwd()
        assert "TASK INSTRUCTIONS:\nsystem" in kwargs["input"]
        assert "INPUT DATA:\nuser" in kwargs["input"]
        assert kwargs["timeout"] == 600
        output.write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="event log, not JSON", stderr="")

    with patch("resume_gen.shutil.which", return_value="/test/codex"), patch(
        "resume_gen.subprocess.run", side_effect=fake_run
    ), patch("urllib.request.urlopen", side_effect=AssertionError("API must not be called")):
        assert resume_gen.call_llm_json("system", "user", backend="codex") == {"ok": True}
        assert resume_gen.call_llm_json("system", "user", backend="codex", model="chosen-model") == {"ok": True}
    default_command = invocations[0][0]
    assert "--model" not in default_command
    assert default_command[default_command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in default_command and default_command[-1] == "-"
    assert invocations[1][0][invocations[1][0].index("--model") + 1] == "chosen-model"
    assert all(not Path(kwargs["cwd"]).exists() for _, kwargs in invocations)

    with patch("resume_gen.shutil.which", return_value=None):
        try:
            resume_gen.call_llm_json("s", "u", backend="codex")
        except RuntimeError as exc:
            assert "not found" in str(exc) and "codex login" in str(exc)
        else:
            raise AssertionError("missing executable must fail")

    for result, message in [
        (subprocess.CompletedProcess([], 1, stdout="", stderr="Please log in"), "codex login status"),
        (subprocess.CompletedProcess([], 0, stdout="", stderr=""), "final response"),
        (subprocess.TimeoutExpired("codex", 600), "timed out"),
        (OSError("cannot execute"), "Could not start"),
    ]:
        options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
        with patch("resume_gen.shutil.which", return_value="/test/codex"), patch(
            "resume_gen.subprocess.run", **options
        ):
            try:
                resume_gen.call_llm_json("s", "u", backend="codex")
            except RuntimeError as exc:
                assert message in str(exc)
            else:
                raise AssertionError(f"expected failure: {message}")

    for content in ("", "[]", "not json"):
        with patch("resume_gen._call_codex", return_value=content):
            try:
                resume_gen.call_llm_json("s", "u", backend="codex")
            except (RuntimeError, ValueError):
                pass
            else:
                raise AssertionError("invalid Codex response must fail")


def test_codex_cli_pipeline() -> None:
    # Exercise both CLI commands through the real dispatcher without an API key or network.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "resume.txt"
        source.write_text("Candidate built services.", encoding="utf-8")
        profile_path = root / "profile.yaml"
        jd = root / "jd.txt"
        jd.write_text("Python engineer", encoding="utf-8")
        profile = {"basics": {"name": "Candidate"}, "skills": ["Python"], "roles": [
            {"company": "C", "title": "T", "bullets": ["Built services."]}
        ]}
        draft = {"skills": ["Python"], "extracted_keywords": ["Python"], "roles": [
            {"company": "C", "title": "T", "bullets": [{"text": "Built services.", "is_custom": True}]}
        ]}
        with patch("resume_gen._call_codex", side_effect=[json.dumps(profile), json.dumps(draft), json.dumps(draft)]) as call, patch(
            "urllib.request.urlopen", side_effect=AssertionError("API must not be called")
        ):
            common = ["--backend", "codex", "--api-key", ""]
            assert resume_gen.main(common + ["ingest", str(source), "-o", str(profile_path)]) == 0
            assert resume_gen.main(common + ["tailor", "-p", str(profile_path), "-j", str(jd),
                                            "-o", str(root / "out"), "--custom-bullets", "1"]) == 0
            assert call.call_count == 3
            assert all(c.args[2] is None for c in call.call_args_list)
        for suffix in (".pdf", ".docx", "_report.json"):
            assert (root / "out" / f"tailored_resume{suffix}").stat().st_size > 0
        parser = resume_gen.build_parser()
        assert parser.parse_args(["tailor", "-j", "jd.txt"]).backend == "api"


def test_brainstorming_and_stable_selection() -> None:
    import copy
    profile = {"basics": {"name": "Sample"}, "skills": ["Python"], "roles": [
        {"company": "Acme", "title": "Analyst", "dates": "2020-Present", "bullets": ["Cut spend by 28%."]},
        {"company": "Earlier", "title": "Engineer", "dates": "2017-2020", "bullets": ["Built systems."]},
    ], "education": [{"school": "A", "degree": "MS"}, {"school": "B", "degree": "JD"}],
       "certifications": ["CISSP", "Bar"]}
    original = copy.deepcopy(profile)
    draft = {
        "job_analysis": {"target_role": "Risk Lead", "positioning": "Risk and automation", "requirements": [
            {"theme": "Control maturity", "priority": "required", "application": "Show assessment ownership"}]},
        "extracted_keywords": ["GRC"], "skills": ["C2M2", "ServiceNow IRM", "Python", "python"],
        "education_order": [1, 1, True, 99], "certification_order": [1],
        "roles": [{"id": "r1", "company": "Wrong", "title": "Wrong", "dates": "Wrong", "bullets": [
            {"id": "r1.custom1", "text": "Built a maturity roadmap.", "is_custom": True,
             "rationale": "Proposed maturity ownership", "detail_prompts": ["Add stakeholder groups"]},
            {"id": "r1.b1", "text": "Cut spend by 28%, ensuring capacity across 3 regions.", "is_custom": False,
             "is_expanded": True,
             "rationale": "Expanded scope worth considering"},
        ]}],
        "brainstorming": [{"role_id": "r1", "theme": "Adoption", "text": "Trained [number] control owners.",
                            "rationale": "Alternative platform adoption example"}],
        "editorial_notes": ["Compressed older engineering experience"],
    }
    style = {"roles": [{"id": "r1", "bullets": [
        {"id": "r1.b1", "text": "Cut spend by 28%."},  # loses the scope metric, so retain the draft
        {"id": "r1.custom1", "text": "Created a maturity roadmap."},
        {"id": "r1.extra", "text": "Unselected style invention."},
    ]}]}
    with patch("resume_gen.call_llm_json", side_effect=[draft, style]):
        out = resume_gen.tailor_resume(profile, "Maturity leadership", custom_bullet_count=1, api_key="k")
    assert profile == original
    assert out["skills"] == ["C2M2", "ServiceNow IRM", "Python"]  # useful suggestions aren't evidence-filtered
    assert [(r["company"], r["title"], r["dates"]) for r in out["roles"]] == [
        ("Acme", "Analyst", "2020-Present"), ("Earlier", "Engineer", "2017-2020")]
    assert [b["id"] for b in out["roles"][0]["bullets"]] == ["r1.custom1", "r1.b1"]
    assert "3 regions" in out["roles"][0]["bullets"][1]["text"]
    assert out["roles"][1]["bullets"][0]["text"] == "Built systems."
    assert [e["school"] for e in out["education"]] == ["B", "A"]
    assert out["certifications"] == ["Bar", "CISSP"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notes = root / "review.md"
        resume_gen.write_review_markdown(out, notes)
        text = notes.read_text()
        assert "Risk and automation" in text and "Add stakeholder groups" in text
        assert "Trained [number]" in text and "Expanded scope" in text
        docx = root / "draft.docx"
        pdf = root / "draft.pdf"
        resume_gen.write_ats_docx(out, docx)
        resume_gen.write_ats_pdf(out, pdf)
        for artifact in (docx, pdf):
            text = resume_gen.extract_text_from_file(artifact)
            assert "Created a maturity roadmap." in text and "C2M2" in text
            assert "Trained" not in text and "Unselected style invention" not in text
        import zipfile
        with zipfile.ZipFile(docx) as z:
            xml = z.read("word/document.xml").decode()
            assert "w:keepNext" in xml and "w:keepLines" in xml


def test_style_failure_and_draft_repair() -> None:
    profile = {"roles": [{"company": "C", "title": "T", "bullets": ["Did useful work."]}]}
    draft = {"roles": [{"id": "r1", "bullets": [
        {"id": "r1.b1", "text": "Automated failover, ensuring 99.99% uptime across 3 regions.", "is_custom": False}]}]}
    for style in ({}, {"roles": []}, RuntimeError("provider unavailable"), ValueError("bad JSON")):
        with patch("resume_gen.call_llm_json", side_effect=[draft, style]):
            out = resume_gen.tailor_resume(profile, "Automation", custom_bullet_count=0, api_key="k")
        assert out["roles"][0]["bullets"][0]["text"].endswith("99.99% uptime across 3 regions.")
        assert not out["custom_bullets_report"] and out["generation_notes"]
    with patch("resume_gen.call_llm_json", side_effect=[{}, draft, {"roles": []}]) as call:
        out = resume_gen.tailor_resume(profile, "Automation", custom_bullet_count=0, api_key="k")
        assert call.call_count == 3 and out["roles"]
    with patch("resume_gen.call_llm_json", side_effect=[ValueError("bad JSON"), draft, {"roles": []}]) as call:
        assert resume_gen.tailor_resume(profile, "Automation", custom_bullet_count=0, api_key="k")["roles"]
        assert call.call_count == 3
    with patch("resume_gen.call_llm_json", side_effect=[{}, {}]) as call:
        try:
            resume_gen.tailor_resume(profile, "Automation", api_key="k")
        except RuntimeError as exc:
            assert "one repair" in str(exc) and call.call_count == 2
        else:
            raise AssertionError("empty draft must fail after one repair")


def test_pdf_metrics_and_block_pagination() -> None:
    import re
    assert abs(resume_gen._pdf_text_width("Hello", 10) - 22.78) < 0.001
    assert resume_gen._pdf_text_width("W", 10, bold=True) == 9.44
    assert resume_gen._pdf_text_width("(test)", 10) > resume_gen._pdf_text_width("test", 10)
    assert resume_gen._pdf_text_width("–", 10) == resume_gen._pdf_text_width("-", 10)
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "blocks.pdf"
        resume = {"basics": {"name": "Sample"}, "roles": [{
            "title": "Senior Governance Risk and Compliance Analyst " * 3, "company": "Long Company " * 3,
            "location": "Somewhere", "dates": "2020-Present", "bullets": [
                {"text": f"Bullet{i}: " + "Maintained controls and updated documentation. " * 3} for i in range(18)]}],
            "education": [{"school": "SchoolOne", "degree": "MS"}, {"school": "SchoolTwo", "degree": "JD"}],
            "skills": ["Risk management", "Automation"]}
        resume_gen.write_ats_pdf(resume, pdf)
        text = resume_gen.extract_text_from_file(pdf)
        pages = text.split("\f")
        assert len(pages) >= 3
        assert any("SchoolOne" in page and "SchoolTwo" in page for page in pages)
        assert "(continued)" in text
        for i in range(18):
            assert text.count(f"Bullet{i}:") == 1
        # Actual text operators, rather than PDF source string lengths, must stay inside the margins.
        raw = pdf.read_bytes().decode("latin-1")
        coords = re.findall(r"Tf ([\d.]+) ([\d.]+) Td", raw)
        assert coords and all(43 <= float(y) <= 749 for _, y in coords)


def test_final_changes_are_visible_without_model_flags() -> None:
    profile = {"skills": ["Python", "NIST"], "roles": [{"company": "Acme", "title": "Analyst", "bullets": [
        "Assessed NIST controls.", "Maintained documentation.", "Supported 12 audits."
    ]}]}
    resume = {"skills": ["python", "NIST CSF", "ServiceNow IRM"], "roles": [
        {"id": "r1", "company": "Acme", "title": "Analyst", "bullets": [
            {"id": "r1.b1", "text": "Assessed NIST CSF and COSO controls.", "is_expanded": False},
            {"id": "r1.b2", "text": "Maintained documentation."},
            {"id": "r1.b3", "text": "Supported 12+ audits."},
            {"id": "r1.custom1", "text": "Built a control roadmap.", "is_custom": True,
             "detail_prompts": ["Check control domains and your ownership."]},
            {"id": "r1.unknown", "text": "Trained control owners.", "is_custom": False},
        ]}], "brainstorming": [{"text": "OPTIONAL alternative, not included."}]}
    changes = resume_gen.build_changes_report(profile, resume)
    bullets = {c["id"]: c for c in changes if c["kind"] != "added_skill"}
    assert set(bullets) == {"r1.b1", "r1.b3", "r1.custom1", "r1.unknown"}
    assert bullets["r1.b1"]["original_text"] == "Assessed NIST controls."
    assert bullets["r1.b1"]["text"] == "Assessed NIST CSF and COSO controls."
    assert bullets["r1.b1"]["kind"] == "rewritten_bullet"
    assert bullets["r1.b3"]["original_text"] == "Supported 12 audits."
    assert bullets["r1.custom1"]["kind"] == "custom_bullet"
    assert bullets["r1.unknown"]["original_text"] is None
    assert bullets["r1.unknown"]["kind"] == "new_bullet"
    assert [c["text"] for c in changes if c["kind"] == "added_skill"] == ["NIST CSF", "ServiceNow IRM"]
    text = resume_gen.format_changes_markdown(changes)
    assert "Assessed NIST controls." in text and "Assessed NIST CSF and COSO controls." in text
    assert "Check control domains and your ownership." in text
    assert "Maintained documentation" not in text and "OPTIONAL" not in text
    assert "12+ audits" in text and "NIST CSF; ServiceNow IRM" in text
    assert "No changed bullets" in resume_gen.format_changes_markdown([])


def test_omission_advice_never_removes_exported_entries() -> None:
    import copy
    profile = {"certifications": ["CISSP", "Security+ (2018-2021)"],
               "education": [{"school": "Tech University", "degree": "MS Computer Science"},
                             {"school": "State University", "degree": "BA International Relations"}],
               "roles": [{"company": "Acme", "title": "Analyst", "bullets": ["Assessed controls."]}]}
    original = copy.deepcopy(profile)
    draft = {"certification_order": [1, 0], "education_order": [1, 0], "roles": [
        {"id": "r1", "bullets": [{"id": "r1.b1", "text": "Assessed controls."}]}],
        "omission_suggestions": [
            {"section": "certifications", "index": 1, "reason": "CISSP is more relevant to this senior role.",
             "benefit": "Give risk leadership more space."},
            {"section": "education", "index": 1, "reason": "The technical master's is more relevant."},
            {"section": "certifications", "index": 1, "reason": "Duplicate suggestion"},
            {"section": "education", "index": 99, "reason": "Unknown entry"},
            {"section": "roles", "index": 0, "reason": "Wrong section"},
            {"section": [], "index": 0, "reason": "Malformed section"},
            {"section": "education", "index": True, "reason": "Boolean is not an index"},
            {"section": "education", "index": 0, "reason": ""},
        ]}
    with patch("resume_gen.call_llm_json", side_effect=[draft, draft]):
        out = resume_gen.tailor_resume(profile, "Senior IT risk lead", custom_bullet_count=0, api_key="k")
    assert profile == original
    assert out["certifications"] == ["Security+ (2018-2021)", "CISSP"]
    assert len(out["education"]) == 2 and len(out["roles"]) == 1
    assert len(out["omission_suggestions"]) == 2
    assert out["omission_suggestions"][0]["text"] == "Security+ (2018-2021)"
    assert out["omission_suggestions"][1]["text"] == "BA International Relations | State University"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        resume_gen.write_review_markdown(out, root / "notes.md")
        notes = (root / "notes.md").read_text()
        assert "Optional omissions for later editing" in notes
        assert "Give risk leadership more space" in notes and "every" in notes.lower()
        for extension, writer in (("docx", resume_gen.write_ats_docx), ("pdf", resume_gen.write_ats_pdf)):
            path = root / f"draft.{extension}"
            writer(out, path)
            text = resume_gen.extract_text_from_file(path)
            assert "Security+ (2018-2021)" in text and "BA International Relations" in text
            assert "CISSP is more relevant" not in text
    assert "No specific" in resume_gen.format_omission_suggestions([])


if __name__ == "__main__":
    test_omission_advice_never_removes_exported_entries()
    test_final_changes_are_visible_without_model_flags()
    test_brainstorming_and_stable_selection()
    test_style_failure_and_draft_repair()
    test_pdf_metrics_and_block_pagination()
    test_codex_backend()
    test_codex_cli_pipeline()
    test_humanizer_deterministic()
    test_custom_bullets_cli_arg()
    test_merge_extras_and_shape_guards()
    test_custom_bullet_count_warns()
    test_custom_bullets_restored_when_humanizer_drops_them()
    test_dotenv_values_and_empty_jd()
    test_payload_temperature_and_pdf_edges()
    test_role_and_bullet_matching()
    test_retry_serialization_and_empty_bullets()
    test_call_llm_json_and_bad_docx()
    test_ingest_merge_and_tailor_pipeline()
    print("ALL TESTS PASSED")
