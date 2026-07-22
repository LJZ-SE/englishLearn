# 30k Content Library SDD Progress

Branch: `feat/content-library-30k`
Worktree: `/Users/lijiazhi/Documents/Codex/2026-07-22/zhao/.worktrees/content-library-30k`
Baseline: `a0b165a`

Pending sequence:

1. Foundation Tasks 1-6
2. App Integration Tasks 1-6
3. Production Tasks 1-5

Task Foundation 1: complete (commits a0b165a..b1844af, review clean; controller verification 36 passed, Ruff clean).
Task Foundation 2: complete (commits b1844af..8b75fe8, review clean after two fix loops; controller verification 46 passed, Ruff clean).
Task Foundation 3: complete (commits 8b75fe8..233302b, review clean after two fix loops; controller verification 60 passed, Ruff and uv lock check clean).
Task Foundation 4: complete (commits 233302b..7a28914, review clean after three fix loops; controller verification 87 passed, Ruff clean).
Task Foundation 5: complete (commits 7a28914..59cf8b7, review approved after two fix loops; controller verification 105 passed, Ruff and uv lock check clean).
Task Foundation 6: complete (commits 59cf8b7..5b623c4, review clean; controller verification 106 passed, Ruff clean).
Task App Integration 1: complete (commits 5b623c4..bda0583, review clean after one fix loop; controller verification 120 passed, Ruff and diff checks clean).
Task App Integration 2: complete (commits bda0583..9ced245, review clean after one fix loop; controller verification 240 non-Qt passed, Ruff and diff checks clean).
Task App Integration 3: complete (commits 9ced245..fbf6d3b, review clean after one fix loop; controller verification 251 non-Qt plus 14 controller passed, Ruff and diff checks clean).
Task App Integration 4: complete (commits fbf6d3b..3108ada, review clean after three fix loops; controller verification 270 non-Qt plus 9 Qt-serial passed, Ruff and diff checks clean).
Task App Integration 5: complete (commits 3108ada..6055de5, review clean after one fix loop; controller verification 274 non-Qt plus 13 Qt-serial passed, Ruff and diff checks clean).
Task App Integration 6: complete (commits 6055de5..2f39c83, review clean; controller verification performance sample median 1.49 ms/get median 0.23 ms, 276 non-Qt plus 13 Qt-serial passed, Ruff and diff checks clean).
Task Production 1: complete (commits 2f39c83..8c31a76, review clean after five fix loops; controller verification 140 content tests passed, source lock verified, raw 641445/Wikinews 2590/provenance missing 0, Ruff and diff checks clean).
Task Production 2: strict classifier and first targeted-source checkpoint complete, overall task still incomplete pending additional labeled corpora, exact selection, and final independent review. Commits through d3d4d68; source and whitelist reviews PASS; controller verification 289 content tests passed and Ruff clean. Real DB v13 now has 903168 raw, 358324 clean accepted, 334332 dedupe accepted, 26962 classified candidates; quota-aware read-only capacity is 17519/30000 with shortage 12481; protected selected stage remains untouched at 0. Classification methods: keyword 12940, context_keywords 8089, single_keyword_whitelist 3803, candidate_source 2130, llm_repair 300, out_of_candidate_pool 307370. Imported targeted sources: DailyDialog 102979, MTS-Dialog 15700, MultiWOZ 143044; source lock verified complete with no pending identities.

Minor findings carried forward:

- Task Foundation 5: explicit `JPY/CNY` plus `¥` is conservatively flagged because `AMBIGUOUS_YEN` is not collapsed when a clear currency token is present (`translation.py`).
