# Resume generation improvement plan

## Objective and division of responsibility

Generate persuasive, specific, well-written resume drafts and brainstorm what the candidate could include for each job. The profile supplies career context and voice; it is not an exhaustive boundary on possible experience.

The user reviews, verifies, edits, and selects generated items after the skill runs. Factual verification, evidence restrictions, approval gates, and confirmation questions are not prerequisites for generation.

“10/10” means excellent positioning, useful content ideas, natural writing, thoughtful selection, and polished documents. It does not guarantee hiring outcomes. The script and skill now implement this plan; execution results and remaining verification limits are recorded in `output/evaluation/comparison.md`.

## Retained constraints

- Keep the single-file Python 3.9+ design, provider support, and existing dependency footprint unless a demonstrated need justifies a change.
- Preserve existing commands and profile compatibility. Do not rewrite the private profile or overwrite the sample outputs during evaluation.
- Retain Certifications → Work Experience → Education → Skills and no summary by default.
- Keep custom bullets in the delivered draft. Retain the default of three and allow zero.
- Identify generated proposals and substantive expansions in the companion report, without cluttering the resume with verification labels.
- Preserve current user edits and uncommitted repository changes.

## Phase 1 — Establish a baseline

Use HCSC, Valvoline, and SentinelOne as comparative examples. Freeze the exact JD text with source URL and retrieval date. Record the observed weaknesses: generic custom bullets, keyword-heavy skills, weak ordering, unnecessary older content, destructive cleanup, heading/date collisions, and almost empty second pages.

Use synthetic regression fixtures in the repository; keep private candidate data outside shareable fixtures. Generate revised examples into separate directories.

Completion: a reproducible before/after comparison covering positioning, brainstorming usefulness, writing, selection, and layout.

## Phase 2 — Improve job analysis and brainstorming

Change the first-pass prompt and report structure in `tailor_resume`.

- Extract principal responsibilities, required/preferred qualifications, working context, and practical problems the hire will solve. Go beyond a flat keyword list.
- Choose a positioning strategy: legal/privacy advisor for HCSC, risk/control program owner for Valvoline, and hands-on audit/security-risk specialist for SentinelOne.
- Infer plausible adjacent responsibilities, accomplishments, examples, tools, and domain exposure worth considering. Do not reject useful ideas merely because the profile does not mention them.
- Draft custom bullets that address important missing themes and fit the assigned role's seniority and business context. Keep them in the resume draft.
- Explain each proposal's purpose in the report: the requirement it addresses, why it fits, and details the user could add or change afterward.
- Offer a small set of meaningfully different alternatives when useful. Keep alternatives separate from the bullets actually rendered and from the requested custom-bullet count.
- Brainstorm useful scope and outcome details: stakeholders, control domains, systems, adoption, turnaround, risk decisions, and business impact. Use placeholders in optional variants when a specific number is needed rather than fabricating precise metrics.
- Permit relevant JD skills as suggestions. Replace the current allowlist behavior with editorial selection so useful ideas survive without turning Skills into a copy of the JD.
- Keep the default of three custom bullets, allow `--custom-bullets 0`, and report count shortfalls without blocking output.

Completion: a strong draft and practical content ideas arrive without a preliminary verification interview.

## Phase 3 — Improve selection and positioning

- Rank bullets by relevance, specificity, accomplishment, and distinct contribution. Put the best matches first; generated bullets should not always be appended last.
- Allocate space by relevance and recency. Shorten unrelated older roles while preserving career chronology.
- Combine overlapping bullets and repeated tool/framework references while preserving genuinely different achievements.
- Use roughly 12–18 skills as an editorial starting point, not a quota. Consolidate repeated SOC 2, ISO, ITGC, reporting, and platform entries.
- Prioritize credentials appropriate to the target role. Present dated credentials as optional editing choices in the report; do not alter the profile.
- Preserve useful existing metrics and make their business significance clear.

Completion: each output tells a coherent story rather than repeating the same history with extra keywords.

## Phase 4 — Make editing improve the writing

Keep two model passes initially; do not add a third automatic critic pass before evaluating the revised workflow.

- Pass 1 analyzes the role, selects and orders content, and drafts possibilities.
- Pass 2 improves clarity, specificity, rhythm, and voice. It edits selected text rather than replanning the document or discarding proposals.
- Introduce stable role/bullet IDs in working data so reordering and rewriting do not depend on fuzzy matching. Keep employment metadata intact unless the user requests changes.
- Remove destructive clause deletion. Rewrite meaningful outcomes such as “ensuring 99.99% uptime across 3 regions” rather than deleting them.
- Treat stock-word lists as editorial guidance instead of unconditional replacements. Permit natural technical language and varied sentence structure.
- Avoid forcing every bullet into the same action/metric formula or two-sentence pattern.
- Validate response structure and IDs. If editing is empty, malformed, or loses selected content, preserve the usable first draft.
- Allow one targeted structural repair, then return the best usable draft with a precise limitation. Avoid indefinite repair loops.

Completion: the editor improves prose without losing important outcomes, roles, selected bullets, or requested custom content. Structural validation protects usable output, not factual eligibility.

## Phase 5 — Repair DOCX and PDF layout

Use the same selected content for both formats.

- Fix the LaunchDarkly heading/date collision through predictable wrapping or separate metadata lines.
- Replace approximate PDF widths with accurate metrics for the existing fonts, without adding a general rendering framework.
- Keep headings with content, degree entries together, and ordinary bullets together where practical. Permit controlled splitting for oversized blocks.
- Add matching paragraph keep rules and long-heading wrapping to DOCX.
- Favor readable type and spacing. Two balanced pages are preferable to a crowded first page and a fragment on page two.
- Resolve overflow through content selection before reducing font size.
- Check unsupported characters and text extraction; provide a usable DOCX fallback where PDF fonts cannot represent text.
- Render and inspect every page of both formats. Separately check for missing or duplicated content.

Completion: the three examples have no collisions, awkward Education splits, or avoidable skills-only spillover.

## Phase 6 — Deliver a useful editing report

Extend the JSON report while retaining compatible fields, and add a concise Markdown companion report containing:

- Target role, recommended positioning, and principal job themes.
- Custom bullets and other substantive expansions, with their role and rationale.
- Additional accomplishments or responsibilities worth considering.
- Optional alternate wording and detail prompts for the user's later editing.
- Content omitted or compressed and the editorial reason.
- Presentation notes and actual generation limitations.

Clearly distinguish included content from optional ideas. Do not require responses before generating, treat brainstorming as a failure, or claim a fabricated ATS score.

Completion: the user can understand the strategy and edit the draft efficiently after the skill completes.

## Phase 7 — Update the agent skill and documentation

Update `SKILL.md` alongside corresponding script changes, then align `README.md` and `AGENTS.md`.

- Describe a drafting and brainstorming workflow, followed by user verification and editing.
- Retrieve the exact JD or use supplied text. Identify an exact-job reproduction when necessary and disclose the source limitation rather than substituting a different role.
- Use the profile for context, strengths, voice, and plausible expansion. Missing detail should prompt useful proposals, not a halt.
- Generate the draft, review selection and writing, inspect both rendered exports, and repair demonstrated issues before delivery.
- Preserve custom content and document expansions in the report. Do not introduce confirmation questions or approval gates before generation.
- Avoid generic advice, keyword stuffing, rigid quotas, or ATS success guarantees.
- Keep review/repair bounded and report real limitations if rendering or source access is unavailable.
- Keep the skill concise and self-contained. Add supporting references only when their reusable value justifies them.

Completion: skill instructions, CLI behavior, and reporting agree. Structural validation and behavioral evaluation are reported separately.

## Verification

### Offline regression tests

Extend `test_resume_gen.py`; call every new test from its `__main__` block. Cover:

- Zero/positive custom counts, proposal preservation, and reordered content.
- Useful JD skill suggestions surviving despite absence from the profile.
- Separation of rendered bullets from optional report alternatives.
- Stable IDs through rewriting, reordering, and restoration.
- Preservation of metrics and meaningful clauses during cleanup.
- Empty/malformed style responses and usable-draft fallback.
- Report/DOCX/PDF content parity, long headings, Education entries, and pagination.
- Previous-output protection after rendering failure.

Run `python3 test_resume_gen.py`. Replace tests that currently require substantive information loss. Factual verification is outside the current acceptance scope.

### Skill behavior scenarios

Define expectations before rewriting:

1. Normal request: produce a strong-match GRC draft, contextual proposals, concise report, and visually checked exports.
2. Sparse profile: propose relevant COSO/C2M2/IRM or legislative experience possibilities without requiring answers first; identify expansions in the report and avoid fabricated precise metrics.
3. Editing failure: recover a dropped role or custom bullet and complete the draft without unnecessary interruption.
4. Neighboring request: explain a posting without generating resumes or modifying the profile.

Evaluate decisions and artifacts, not exact wording. Use isolated directories. Do not incur material API cost solely for evaluations without authorization. Delegate only when authorized.

### Three-job acceptance review

Regenerate against frozen JDs and the same profile:

- HCSC: emphasize the legal/privacy bridge and brainstorm specific research, summaries, and business guidance.
- Valvoline: foreground risk/control ownership and propose maturity reporting, remediation, and platform adoption examples.
- SentinelOne: prioritize audit testing, remediation, customer assurance, policies, and technical security examples.

Compare positioning, brainstorming, writing, selection, and layout. Record specific improvements and remaining weaknesses rather than automatically assigning 10/10. Acceptance requires passing offline checks and skill validation, exercised behavioral scenarios where available, material improvement in all three samples, and visual inspection of every page of both formats. State which model-backed evaluations actually ran.

## Implementation order

1. Baseline and job-analysis/brainstorming schema.
2. Relevance selection, custom proposals, and editing report.
3. Safe editing, stable IDs, and structural fallback.
4. DOCX/PDF layout repairs.
5. Skill/documentation alignment and behavioral evaluation.
6. Three-job regeneration and comparative review.

Defer provenance systems, strict evidence filtering, factual approval workflows, and automatic claim confirmation unless the user later requests them.
