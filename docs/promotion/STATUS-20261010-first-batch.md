# LFL promotion / 2026-10-10 / evidence-based publishing status

> Operational status, not a marketing claim. Updated after read-only checks on 2026-10-10 evening (Asia/Shanghai).
> Count a publication only after the exact public URL is observed. Do not infer approval from a published page.

## Final in-place correction result (supersedes earlier pending statuses below)

**Execution outcome: 5/5 existing canonical public article IDs updated in place, 20/20 approved online illustrations actually fetched and visually verified, 2/2 duplicate public articles' normalized text unchanged, 0 new articles, 0 deletions.** Every public page was reopened after submission and its corrected content checked. Earlier historical `PENDING`, `REVISE`, and “not yet online synced” notes below describe the **earlier review stages**, not this final outcome.

Authoritative machine-readable after-verify receipt: `docs/promotion/receipts/20261010-inplace-updates.json`.

| Canonical published page | Exact retained ID | Final result | Approved source |
| --- | --- | --- | --- |
| Zhihu · daily-02 | `https://zhuanlan.zhihu.com/p/2092313733624238657` | **PUBLIC VERIFIED** — unsupported AACL assertions removed; paper ID preserved; 5 figures including replaced fig8 | `daily-02-r3.md` |
| Zhihu · daily-03 | `https://zhuanlan.zhihu.com/p/2092334918437230422` | **PUBLIC VERIFIED** — correct historic v0.6.28/805/161,472/272 and 27 RULE-AI/26+6; four approved figures, interrupted sentence repaired | `daily-03-r2.md` |
| Toutiao · daily-01 | `https://www.toutiao.com/article/7694948729350111759/` | **PUBLIC VERIFIED** — currentness/CHANGELOG corrections, two approved figures | `daily-01-r3.md` |
| Toutiao · daily-02 | `https://www.toutiao.com/article/7694972102780240418/` | **PUBLIC VERIFIED** — unsupported AACL claims removed; original paper ID, five approved figures including corrected fig8 | `daily-02-r3.md` |
| Toutiao · daily-03 | `https://www.toutiao.com/article/7694988135675085327/` | **PUBLIC VERIFIED** — factual counts and version corrected; only four approved figures remain | `daily-03-r2.md` |

Visual media test: for each public article, inspect the site's actual CDN `data-src`/`data-original`, download and decode image bytes, verify dimensions and compare its grayscale pixels against the local LFL-approved image. **20/20 PASS** (40×40 grayscale RMS range 0.45–1.45; platforms recompressed images, so raw file SHA equality is not expected). Exact approved image counts per above = 5+4+2+5+4.

Before/after recoverable evidence: `docs/promotion/receipts/preedit-20261010/` and `docs/promotion/receipts/postedit-20261010/`, **each 7 URL × (HTML + TXT + JSON)** with source URL, UTC observation time, content SHA256 and snapshot checks. Five canonical posts have changed text SHA; the duplicate Zhihu `2092310847452463615` and duplicate Toutiao `7694991672115053071` retain their **exact original whitespace-stripped text SHA**. They were not edited, deleted, or unpublished. Backups are evidence copies, not an automatic platform rollback guarantee.

**Accounting:** This was correction of 5 preexisting publications, **not 5 new publications**. Unique topics remain **3**. Git staging/commit/push was not performed; keep previously existing dirty worktree and release branch untouched. The standing daily writing automation is separate and still subject to LFL review, de-duplication and per-platform authorizations.

Final workspace status check observed branch `release/v0.6.29` at `8a56bff20c71` (the repository advanced independently since the earlier observed `372a31d41191`); no staged paths were present. The historical article-review snapshot remains `main@692aef75218e` and must not be confused with the current moving branch HEAD.

## Editorial gate: all three exact revised sources PASS (updated after r3 review)

| Topic | Exact revised file | SHA-256 | LFL editorial verdict | Online sync |
| --- | --- | --- | --- | --- |
| daily-01 / agent memory | `docs/promotion/revisions/20261010/daily-01-r3.md` | `d091672322f575e53d0a0fda71e29d98525608afa039798365295861038bedb5` | **PASS** (narrow r3 read-only review) | Toutiao canonical older post now corrected and publicly checked |
| daily-02 / self-improvement judgment | `docs/promotion/revisions/20261010/daily-02-r3.md` | `597e97181923a400476b8bae78c429c7184b24d3ab23a6e33e937f12f5eefb9d` | **PASS** (LFL 21:44 local review) | Zhihu and Toutiao canonical older posts now corrected; extra duplicate Zhihu article intentionally untouched |
| daily-03 / architecture philosophy | `docs/promotion/revisions/20261010/daily-03-r2.md` | `7b3b6a7537ba39e0e73cafda8a88daa8d01ab0888354c7b2381315af6b14a4f0` | **PASS** (LFL 21:53 local review) | Zhihu and Toutiao canonical older posts now corrected; extra duplicate Toutiao article intentionally untouched |

**Important**: the table below still records the *original* drafts, which received REVISE. PASS of a later exact-source revision does not retroactively make an earlier draft, or an already-published variant, identical to the approved version. No new platform publication or existing-page correction has been performed in this audit.

The daily-01-r3 PASS was given for removal of the defective fig3. Subsequent file verification confirmed 163 lines and exact claimed hash; `diff -u` against r2 shows only removal of four lines (the image, caption and spacing). Retained fig1 SHA256 `7e2f7d2f11abdb23496875dbb729cc8c6d37094df0185b45a1f8d5c6ab54b0c4`, fig5 SHA256 `cfadfad9dc73c3260a516af4c0282e27d96b4ca6687f030ffefbb198deaf1241`. The original, r2 and figures were not overwritten.

The repository subsequently advanced from the historical reviewed snapshot `main@692aef75218e` to observed current branch `release/v0.6.29@372a31d41191`. Historical article figures intentionally refer to their stated 2026-10-10 snapshot; do not silently reinterpret as live statistics at the newer HEAD.

## Editorial assets (local workspace)

| ID | Local source | SHA-256 of current source | LFL editorial audit | Public evidence |
| --- | --- | --- | --- | --- |
| daily-01 | `docs/promotion/20261010-lfl-daily-01.md` | `a11f786a01e5d1421e996111fb4ff9807419666b22de9ebc4f0da5f43de14c52` | **REVISE** | None verified |
| daily-02 | `docs/promotion/20261010-lfl-daily-02.md` | `c918c234bd2190f604ecc5eff8f82bd0d4b786bcf06898274f508effc75a894c` | **REVISE** | Zhihu has same-titled items, identities pending |
| daily-03 | `docs/promotion/20261010-lfl-daily-03.md` | `c1962e2f624ce0fd689809c4c52aa8ecc04adfdab4a5295106552eb76960e307` | **REVISE** (already public; published page requires errata) | [Zhihu article](https://zhuanlan.zhihu.com/p/2092334918437230422) |

Repo read-only review anchor: `main@692aef75218e` / `v0.6.28-12-g692aef752`; uncommitted daily-02 and untracked daily-03 already existed and must not be overwritten.

## Observed publication and account status

### Exact live inventory resolved (subsequent read-only verification)

Machine-readable audit receipt: `docs/promotion/receipts/20261010-publication-inventory.json`. **Seven exact article URLs** were individually opened, identifying **three topic families**. These seven public articles existed before this verification; **zero newly submitted posts** in this run. The creator profile is not an article URL, so it is not counted as proof on its own.

| Platform | Topic | Actual article URL | Finding |
| --- | --- | --- | --- |
| Zhihu | 02 A | `https://zhuanlan.zhihu.com/p/2092313733624238657` | Complete ending; 6176 non-whitespace text characters, 5 pictures; unverified AACL assertion still present; retain candidate |
| Zhihu | 02 B | `https://zhuanlan.zhihu.com/p/2092310847452463615` | First 6176 non-whitespace characters **exactly match** 02 A, followed by ~3529 extra characters repeating the beginning; malformed duplicate, not a separate article |
| Zhihu | 03 | `https://zhuanlan.zhihu.com/p/2092334918437230422` | Existing public old draft still contains v0.6.27 |
| Toutiao | 01 | `https://www.toutiao.com/article/7694948729350111759/` | Old snapshot/version still visible |
| Toutiao | 02 | `https://www.toutiao.com/article/7694972102780240418/` | Unverified AACL assertion still visible |
| Toutiao | 03 A | `https://www.toutiao.com/article/7694991672115053071/` | Duplicate: same normalized body SHA as 03 B |
| Toutiao | 03 B | `https://www.toutiao.com/article/7694988135675085327/` | Duplicate: same normalized body SHA as 03 A, older timestamp and more descriptive title; retain candidate |

**Conclusion:** editorial review is 3/3 PASS for the *revised files*, but **none of the seven existing public pages has yet been verified to match those exact revised versions**. Do not post more copies. Before in-place edits, back up and verify the actual platform editor; preserve existing publication IDs. Deletion or unpublishing of duplicates needs explicit owner approval and successful recovery/backup preflight.

### 2026-10-10 read-only recovery and editor preflight

- **Pre-edit backup captured successfully (7/7)**: `docs/promotion/receipts/preedit-20261010/` contains one exact, read-only public-page article `.html`, `.txt`, and `.json` (with title, URL, observation time and hashes) for **each of the seven listed URLs**. These are recovery/reference snapshots of the original public articles, not platform exports or guarantees that an old publication can be rolled back automatically.
- **Zhihu canonical editor available**: `https://zhuanlan.zhihu.com/p/2092313733624238657/edit` opened in the authenticated browser and showed the article-rich-text editor with an `更新` button. **Not clicked.** Do not replace the entire article without a post-edit rendering/image verification and controlled submission.
- **Toutiao content manager available**: use **`https://mp.toutiao.com/profile_v4/manage/content/all?enter_from=left_menu`** (the parent path ending at `/manage/content` only displays navigation, not the work list). The authorized account shows all four relevant LFL posts as `已发布`, with `修改` options. A top banner still says account details need completion to unlock publishing privileges; existing-publication editing eligibility is not yet established. No `修改`/submit was successfully entered or used.
- **Preferred canonical choices only, not deletion authority**: retain the complete, non-concatenated Zhihu daily02 `2092313733624238657`; retain the earlier, descriptive-title Toutiao daily03 `7694988135675085327`. The counterparts `2092310847452463615` (concatenated duplicate) and `7694991672115053071` (byte-identical body duplicate) are candidates for later de-duplication, **not yet approved for deletion**.
- **Controlled update order**: (1) prepare/preview updated content and image mapping against the reviewed SHA for each *keeper* ID; (2) resolve platform editor/account constraints; (3) perform one public edit at a time, re-open final individual URL to verify corrected facts and images, preserve old backup, and record updated timestamp/receipt; (4) obtain separate explicit permission before deleting/unpublishing the two duplicates. Do not publish new copies while these facts remain unsynchronized.

- **Zhihu daily-03**: exact public article URL `https://zhuanlan.zhihu.com/p/2092334918437230422`; browser displayed matching article title and **edited 2026-10-10 19:54**. It was publicly reachable during current check. Publishing happened *before* this new independent audit. Do not describe it as passing that audit until an explicit verdict exists.
- **Toutiao**: account back office can show an article editor, but account banner also requested more information to unlock publishing rights. Publication qualification or public URL is not yet verified.
- **Toutiao LFL-AGENT public profile**: browser opened the author's public page from the account profile link (`https://www.toutiao.com/c/user/55629289142/?enter_from=mp_profile`); public listing showed at least four LFL-related posts: `当大模型开始记住自己：开源框架 LFL`, `AI说"我改进了一下"，你信吗？`, `程序不是大脑，但程序也不该是哑巴`, and `程序不是大脑，但程序也不该是哑巴：LFL 架构哲学`. The two last titles look related and may represent duplicate/revised variants. **Exact article URLs and whether their bodies are identical remain unresolved**. They are not counted as new publications in this review. Do not post those topics again before resolving link identities.
- **Zhihu editor**: writer interface was visible after an initial login redirect; session authentication may vary. Do not assume a new post can be submitted without fresh preflight.
- **Juejin / CSDN**: editing URLs led to login pages on first check. No published URL verified for these channels.
- **Zhihu profile de-duplication**: the public author page `https://www.zhihu.com/people/yyj-76-28/posts` showed **3 articles**. One was titled like daily-03; **two entries displayed the identical daily-02 title**. Their two exact destination URLs/body hashes have not been individually resolved, so treat them as a **suspected duplicate**, not a proven byte-identical repost. Do not submit daily-02 again or delete either item before resolving both identities.
- **Other articles / other platforms**: Unknown. Do not equate not found with absent; check content-management listings before creating a duplicate.

## Audit request and gates

- LFL audit **completed** in isolated Web session `87454a3c-2a7c-4282-974a-24e435f8ebcb` (~21:37 local), tool-grounded read-only/no-publish check of all three articles. Its explicit verdict was **daily-01 REVISE; daily-02 REVISE (closest to PASS); daily-03 REVISE; 0 PASS; 0 REJECT**. No approval for another post.
- Review problems: daily-01 line 45 currentness/stale figures and line 118 export-serve-mcp incorrectly marked unreleased (released with v0.6.28); daily-02 line 13 AACL IJCNLP Main acceptance not established from authoritative primary source, plus fig8 legibility/possible misreading of '蒸馏' as '蒸馆'; daily-03 line 152 inconsistent 29 packages compared with documented 26 top-level packages + 6 ability modules and time-scoping/stale version figures at ~L96/L156. Repo code, key experiment data, arXiv research summaries and figure origin were largely verified; the outstanding issues block publication despite substantive quality.
- **Non-overwriting daily-02 revision candidate**: `docs/promotion/revisions/20261010/daily-02-r3.md` SHA-256 `597e97181923a400476b8bae78c429c7184b24d3ab23a6e33e937f12f5eefb9d`. Removed unverified acceptance claim (leaving arXiv ID); changed all five image paths to valid relative paths; substituted fig8 candidate-label with unambiguous '候选方法（待验证）'. New figure `docs/promotion/img/fig8-four-program-gates-r3.png` SHA-256 `f92cbb3e51a2688b6020ec71c13bcec0d647b71f1b3214e9cb451b9dacfd1ff4`. Original drafts and original image were not overwritten. **LFL tool-grounded r3 review terminal PASS at ~21:44 local**, verified SHA, figure pixels, 5 links, and absence of the unsupported conference-acceptance claim; no remaining editorial blocker. Publication still depends on site login, dedup and confirmation.
- **Non-overwriting daily-01 candidate**: `docs/promotion/revisions/20261010/daily-01-r2.md` SHA-256 `d7aa076ef1e88cf4d32e1089bc1935765cc31be2c8cbe15fcc13a32eb7a20dee`, 3 existing illustrations embedded; corrected released feature/version, annotated `main@692aef75218e` as metric snapshot, refreshed counts (398 Python source files excluding `__init__.py`, 161,472 lines, 805 test files, 272 non-merge commits during Oct 4–10). **Not yet audited or published.**
- **Non-overwriting daily-03 candidate**: `docs/promotion/revisions/20261010/daily-03-r2.md` SHA-256 `7b3b6a7537ba39e0e73cafda8a88daa8d01ab0888354c7b2381315af6b14a4f0`, 4 existing illustrations embedded; replaced incompatible '29' with audit's 26 package + 6 separately classified modules, clarified 27 RULE-AI rules, current released v0.6.28 and timestamp-anchored measured totals. **Not yet audited, and the existing live Zhihu article has NOT been altered.**
- **LFL 21:53 local follow-up verdict**: daily-03-r2 = **PASS** after independent review of exact revision, while daily-01-r2 = **REVISE**, solely because added fig3-papers.png has incomplete/cropped cards and omits a discussed QGMem paper. No public update performed to daily-03.
- **Non-overwriting daily-01-r3 repair**: `docs/promotion/revisions/20261010/daily-01-r3.md`, SHA-256 `d091672322f575e53d0a0fda71e29d98525608afa039798365295861038bedb5`; removed the defective fig3 and its caption, retained two previously vetted illustrations and all technical prose. Narrow read-only LFL review returned **PASS**, zero remaining editorial blockers. Does not authorize duplicate publication or validate older published contents.
- If `REVISE` or `REJECT`, correct the specific sources and re-review the exact new hashes before further publication. For live daily-03, correct the already published article as warranted by the verdict; do not duplicate or delete without a separately justified action.
- If `PASS`, verify current account permissions, rendered figures, platform rules and previous-publication de-duplication; then publish one article at a time, observe final URL and content, and write a receipt including URL/time/title/source SHA and proof status.
- Minimum future daily **new-publication** target: 1 distinct reviewed article, aspirational 3; edits of existing pages never count as new pieces. For the completed first-batch in-place correction, see the final five public links, verified revisions, image counts and after-snapshots at the top of this file.

## Remaining follow-up (after this completed in-place correction)

1. The user's authorization in this run **did not** allow deleting or unpublishing the two known duplicate older articles. Keep them unchanged unless the user explicitly grants separate removal authority and backup/recovery preflight succeeds.
2. Continue **future daily new-topic** article production under the standing 09:00 Asia/Shanghai automation; fresh AI/Agent/Harness evidence, LFL's independent PASS for each exact draft/figure set, site login, de-duplication and exact public URL are mandatory gates. Do not recycle today's corrected topic IDs as new posts.
3. Decide separately whether to commit selected editorial source files, image assets and audit receipts on a dedicated clean branch. Existing dirty working tree and `release/v0.6.29` were intentionally preserved; no git staging, merge, restart or push was performed here.
4. At the next operations review, inspect platform article status, account publishing eligibility and analytics/engagement using current platform self-reports; do not invent traffic gains or engagement metrics from the existence of posts.
