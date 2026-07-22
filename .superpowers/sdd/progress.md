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
Task Production 2: strict classifier and two targeted-source waves complete, overall task still incomplete pending second-wave gap sources, exact selection, and final independent review. Commits through 7934278; source, whitelist, and labeled-corpus reviews PASS; controller verification 348 content tests passed and Ruff clean before real import. Real DB after SGD/CLINC150/MASSIVE import has 1244237 raw, 535900 clean accepted, 460207 dedupe accepted, and 460207 classified candidates. Quota-aware read-only capacity is 22461/30000 with shortage 7539; selected stage remains untouched at 0. Newly imported labeled sources: SGD 330401, CLINC150 3750, MASSIVE 6918. Source lock verified complete with 20 entries and no pending identities. Remaining shortages are concentrated in study, health, technology, and work scenes, so a second explicit-source wave is required before semantic review.
Task Production 2 second-wave checkpoint: AMI/MedQuAD/SciQ implementation independently reviewed PASS and committed at fd7b579. Real fixed imports added AMI 29904, MedQuAD 28305, and SciQ 11679 records; DB now has 1314125 raw, 588561 clean accepted, 504456 dedupe accepted, and 504456 classified candidates. Quota-aware read-only capacity is 23714/30000 with shortage 6286; selected stage remains untouched at 0. The new selected-capacity contribution is AMI 564, MedQuAD 732, and SciQ 315. Work meetings and clinic are now full; pharmacy shortage fell to 196, wellbeing to 33, engineering to 220, and science to 151. Stack Exchange and Taskmaster targeted sources remain pending for the 6286 residual gap.
Task Production 2 targeted-source checkpoint: Taskmaster-2, official Stack Exchange Fitness dump, and three versioned official Stack Exchange API snapshots passed independent parser and integration review. The complete content test suite is 491 passed with Ruff clean. Real imports added Taskmaster movies 10000, Taskmaster sports 10000, Stack Exchange API snapshots 13290, and Fitness dump 15000 records. The DB now has 1362415 raw items, 624307 clean accepted, 537618 dedupe accepted, and 537618 classified candidates. Quota-aware read-only capacity is 27327/30000 with shortage 2673; selected stage remains untouched at 0. Source lock is complete with no pending identities. Remaining work is historical review replay plus bounded semantic review for the 2673-scene residual, followed by exact selection and final review.

Minor findings carried forward:

- Task Foundation 5: explicit `JPY/CNY` plus `¥` is conservatively flagged because `AMBIGUOUS_YEN` is not collapsed when a clear currency token is present (`translation.py`).
