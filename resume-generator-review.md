# Resume matching and recruiter review

## Outcome

The highest-value remaining work is to make job coverage inspectable and tighten recruiter-focused editing. The existing single-column exports and user-confirmed layouts provide a good foundation. Optimizing parsing, discoverability, and the relevance of accomplishments is more useful than claiming a universal ATS pass score.

The user remains responsible for reviewing and verifying generated proposals after the skill completes. This review does not introduce evidence restrictions or approval gates.

## Implemented in this review

- Added `changes_report`, comparing final selected bullets and skill terms with the supplied profile independently of model flags.
- Reports include original and tailored wording, employer, stable bullet ID, rationale, and detail prompts. Unlinked bullets are identified rather than assigned a guessed original.
- Added or reworded skill terms are listed separately. A term absent from the profile is not automatically labeled false or invented.
- Change reports include ordinary rewrites, including ones marked `is_expanded: false`; unchanged bullets and optional alternatives stay outside the included-change list.
- The CLI and Markdown editing report expose the same checklist.
- The skill now requires a visible generated-change section in the final agent conversation. A report link alone does not satisfy delivery.
- Strengthened drafting guidance for the first three relevant bullets, business outcomes, natural exact JD phrases, acronym expansion, and intact historical titles. Strengthened editing guidance to retain important phrases already in the selected text.

All 17 offline test functions passed, including unflagged rewrites, added skills, numeric qualifier changes, optional-alternative separation, the existing generation pipeline, and both model backends. Skill structural validation and whitespace checks passed. Applied the comparison helper to the three existing model-generated drafts without rerunning a model or altering those resumes.

## Remaining improvements in priority order

### 1. Map important requirements to final resume content

The current `job_analysis.requirements` contains a theme, priority, and proposed application. It does not establish which final bullets actually address the requirement. The extracted-keyword list is also an analysis output, not proof of final resume coverage.

Extend the existing analysis with stable requirement IDs and linked bullet IDs. In the editing report, show each important requirement, the selected example, where a useful exact term occurs, and the strongest remaining opportunity. Separate required qualifications, work responsibilities, preferred qualifications, and application conditions. Make clear which links are model judgments and which checks merely observe text presence. Do not call either a factual qualification verdict or ATS score.

### 2. Give the editor concise job priorities and inspect final terms

Pass 2 receives the voice profile and roles, but not the job-analysis priorities. Its task should remain editing rather than replanning; a short target-role/priorities context would help preserve emphasis and business relevance. Prompt guidance now requests important phrase preservation, but the only deterministic content-preservation guard checks numeric substrings.

Add a report of important phrases present, rephrased, or absent after editing. Preserve meaningful acronyms and full names where useful, without treating repetition or stuffing as success. Use phrase boundaries, account for deliberate terminology variants, and describe presence checks as lexical checks rather than semantic matching.

### 3. Evaluate recruiter readability against concrete examples

The selection prompt already asks for relevant bullets and outcomes, but there is no explicit final quality readout. Review whether the top portion shows the role's central work, ownership level, scope, and useful results. Identify vague responsibilities, redundant bullets, excessive framework lists, and long sentences that obscure the point.

Use soft editorial notes, not rigid quotas or fabricated metrics. Prefer one targeted revision using the existing two-pass workflow to another unconditional model pass. Preserve varied natural language and useful detail; a bullet should not be shortened merely to meet an arbitrary word count.

### 4. Check actual exported content on each run

The offline suite and sample comparisons verify export behavior, but normal CLI runs do not automatically compare extracted PDF/DOCX text with the selected content. Add an optional local parse-preview/check using existing extraction tools, covering contact details, job titles, dates, selected bullets, education, skills, and reading order. Report unsupported characters and missing extraction prerequisites explicitly.

Treat this as document integrity and readability testing. It does not establish how an employer's actual ATS will rank or populate every field. No upload to an external ATS or third-party scoring service is necessary for these local checks.

### 5. Suggest lower-value credential omissions in the conversation

The script retains every credential and degree, merely changing their order. The conversation report now offers optional omissions for later editing, with the exact entry, a job-specific reason, and what could receive more emphasis instead. All entries remain in the delivered documents. No omission flags, automatic filtering, or decision before generation is needed. Preserve the source profile and career chronology; a date alone does not establish that a credential is expired.

## ATS evidence and limits

Greenhouse documents keyword filtering where an application's terms must exactly match the searched terms. It also documents parsing problems caused by graphics, columns, complex tables, contact details in headers, and unclear sections. These support natural exact terminology and the existing plain layout. They do not establish a universal ranking formula or hiring outcome.

- [Greenhouse Talent Filtering](https://support.greenhouse.io/hc/en-us/articles/27104809835291-Talent-Filtering)
- [Greenhouse Unsuccessful resume parse](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse)

## Existing-draft change checklists

Stored under the ignored `output/review-audit/` directory:

| Draft | Changed or proposed bullets | Added or reworded skills |
| --- | --- | --- |
| HCSC | 17 | 16 |
| Valvoline | 16 | 12 |
| SentinelOne | 16 | 14 |

These counts include ordinary wording changes and possible aliases. They are editing workload indicators, not counts of fabricated claims. The original resumes were left intact.
