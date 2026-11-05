# Merge handover: land all open PRs into main in one pass

Repo: https://github.com/mepherios/CardModel. Owner rule: GitHub CI is billing-blocked, so **merge on local tests** (a full `python -B -m unittest` from `tests/` plus `CARDMODEL_SELF=0 ./bin/cardmodel verify`). Use the REST API only; GraphQL is blocked.

## 0. Setup
```bash
git clone https://github.com/mepherios/CardModel.git && cd CardModel
git config --add remote.origin.fetch '+refs/heads/claude/*:refs/remotes/origin/claude/*'
git fetch origin
git checkout -b all-merged origin/main
```

## 1. Merge in this order
Run `git merge --no-edit pr-N` for each PR (fetch it first with `git fetch origin pull/N/head:pr-N`). After each **code** PR, run the quick tests for the area it touches. Run the full suite at the end.

1. **#88**: docs bundle. It replaces #72, #73, #74, #76 and #80–#87; close those after the merge.
2. **#65**: handover with the launch checklist.
3. **#42**: fewer CI runs. Merge it early so later pushes cost less.
4. **#50**: pipeline registry, CM50/G_A13, plus #55's purity check and G_A14 (commit 3853c86). #55 is already closed. Run `test_pipeline` and `test_self`.
5. **#38, #41, #47, #36, #35**: CI harness, stdin harnesses, signed zero, reproducible packs, redefinitions.
6. **#60, #61, #62, #71, #75**: sorts and fixed widths (FOUNDATIONS §7). #61 and #62 touch the same width code, so merge #61 first.
7. **#69**: strings in the IR. **Owner approval needed**: its ledger atoms are proposed from index 3425. Do not write atoms to the ledger without a yes. The ledger is append-only (CM43).
8. **#52, #53, #54, #58, #66, #68, #77, #70**: Gödel thread.
   - #77 is stacked on #68.
   - #70 and #77 both edit `cardmodel/engines/godel.py`; keep both functions.
   - #54 **conflicts with main**: resolve it by hand.
9. **#63, #64, #57, #59**: emit fixes, distill UX, numeric laws, showcase.
10. **#67, then #78, then #79**: ARM symbolic.
    - #78 and #79 are both stacked on #67, so expect a conflict in the symbolic files on #79 and keep both features (memory model and loops).
    - **Owner approval needed** for the ARM atoms.
11. **#33, #34**: anyps5 and GB MBC.
12. **#39, #40**: these **conflict with main**. Resolve them last, or skip them and leave them open.
13. **#43**: old snapshot handover. Merge it, or close it as superseded by #65.

## 2. Conflict rules
- Card JSON: do a 3-way merge of the keys, then re-save through `cardmodel.kernel.versioning.save` so the archive is updated (CM14). Never hand-edit a version hash.
- The project card (`cards/project/cardmodel/card.json`) lists branches (CM41): take the union of both sides.
- GOALS.md and LAWS.md: keep both lines, then run `CARDMODEL_SELF=0 ./bin/cardmodel docs --check`.
- If two PRs claim the same CM or G id, stop and ask the owner. This happened before with #50 and #55.
- Gödel purity: content stays a sparse vector, never an integer (CM45), and no new ledger atoms go in without owner approval.

## 3. Verify
```bash
cd tests && python -B -m unittest 2>&1 | tail -20; cd ..
CARDMODEL_SELF=0 ./bin/cardmodel verify
CARDMODEL_SELF=0 ./bin/cardmodel docs --check
```
The full suite took more than 5.5 minutes on 4 cores, so give it at least 30 minutes. Record the pass, fail and skip counts. If a test fails, `git bisect` over the merge commits to find the PR that caused it, then revert that one merge (`git revert -m 1 <sha>`) and leave the PR open with a comment.

## 4. Land
Only after a green local run, and with the owner's go-ahead:
```bash
git push origin all-merged:main
```
GitHub then marks each included PR as merged. For each PR that was skipped, post a REST comment giving the reason. Close #72–#74, #76 and #80–#87 as included in #88.

## 5. Afterwards (owner)
- Fix GitHub billing or the spending limit.
- Delete the branches `claude/ci-exact-int-pow` and `claude/project-thread-3hwg1g`.
- Remove the stray `/addranks.py`.
- Re-measure the canonical-definitions rate (24.6%) and the 0.67% figure quoted in the docs.

Commit trailer for any fix commits: follow the session's attribution instructions. Do not put model names in commits or PRs.
