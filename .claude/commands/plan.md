---
name: plan
description: Create a development plan for a feature or module
context: fork
---

Create a detailed development plan for: $ARGUMENTS

Before planning:
1. Read `AGENTS.md`
2. Read `handoff.md`
3. Read any additional project docs you need

For each step:
1. What files to create/modify
2. Key implementation details
3. How to test it (unit test + manual verification)
4. Dependencies on other steps

Output the plan as a markdown checklist to `docs/plan.md`.
Also update `handoff.md` with:
- current task
- owner
- status
- affected files
- acceptance criteria
- recommended next executor

Do NOT start implementation — plan only.
