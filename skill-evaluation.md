# Resume skill behavioral scenarios

Use isolated output directories and synthetic profiles for reusable regression tests. Evaluate actual decisions and documents, not exact wording or headings. Do not modify the source profile or send applications.

| Scenario | Expected behavior | Observable outcome |
| --- | --- | --- |
| Normal GRC tailoring | Position the candidate around risk/control work; select useful achievements and contextual custom bullets; render both formats | Draft, editing report, and readable pages; IDs and selected content survive editing; the final chat lists generated changes with before/after wording and added skills |
| Sparse profile with COSO/C2M2/IRM or legislative requirements | Brainstorm plausible contextual experience without a preliminary verification interview | Useful proposals included; alternatives and later detail prompts are separate in the report; no made-up precise metrics |
| Style response omits a role/bullet or a metric | Preserve usable selected content and requested proposals | Same selected IDs/order, numerical outcomes retained, fallback described in generation notes |
| Model fails to flag a rewrite or adds skill terms | Compare final content against the profile without restricting proposals | The change report and final chat expose the rewritten bullet and added skill terms even when is_expanded is false; optional alternatives remain separate |
| Dated or weakly related credentials | Suggest optional omissions in the conversation for later user editing | Specific entries and job-related reasons appear in the report; all credentials/degrees remain in DOCX/PDF and the source profile; no decision blocks generation |
| Explain a posting only | Explain the job without running the generator | No profile edits or resume files |

For real examples use HCSC, Valvoline, and SentinelOne against frozen JDs, retaining before/after files. Record positioning, brainstorming usefulness, writing, selection, and visual usability independently. Do not infer behavioral success from structural validation. Record model/host and actual executions; offline mocks do not count as live model evaluations. Obtain any required execution authorization for model-backed runs; no additional resume-content approval gate is needed.
