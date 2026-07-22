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
Task Production 2: fix checkpoint committed, still awaiting source expansion + independent review (strict dry-run selected 28255/30000, shortage 1745 across 10 scenes; stale 30000-row snapshot is not releasable; llm_required 0; 185 content tests passed, Ruff, uv lock, and diff checks clean).

Minor findings carried forward:

- Task Foundation 5: explicit `JPY/CNY` plus `¥` is conservatively flagged because `AMBIGUOUS_YEN` is not collapsed when a clear currency token is present (`translation.py`).
