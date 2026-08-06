# Product report schema

Keep the user-facing report focused on product functionality and UI/UX. Keep ADB,
helper, timing, and tool-retry details in the internal run log unless they create a
visible product issue. Keep claims tied to evidence; use “未验证” when a page or
control was not visited.

The user-facing report is an analysis deliverable, not an operation log. Do not put
raw taps, coordinates, retry history, installation steps, or a long action timeline in
the main body unless they explain a visible product problem. Lead with the product's
positioning, information architecture, functional value, UX strengths, weaknesses,
and—when the scope is only one product—call the comparison section a “竞品分析基线”
instead of implying a completed multi-product benchmark.

Abstract volatile data by default. Replace account-dependent counts, balances, progress,
dates, prices, coupon amounts, badges, usernames, and status values with categories such
as “当前可享权益数量”“当前成长进度”“会员有效期”“优惠金额”. Preserve exact values
only when the user explicitly asks for a snapshot or data comparison.

## 1. Executive summary

- Task and scope
- Result: completed / partial / blocked
- One-sentence product conclusion
- Three most important takeaways

## 2. Functional modules

Use a table like this:

| Module | Purpose | What was visible/verified | UX impression |
|---|---|---|---|
| | | | Clear / mixed / weak |

Prioritize modules the user asked about: entry, membership status, benefits, activity,
coupon/wallet, orders, settings, or other visible sections. Do not list every tiny UI
element.

## 3. UI/UX strengths

Write 2–5 specific strengths, such as discoverability, information hierarchy, visual
consistency, feedback, trust, or scanability. Each item should cite a screenshot.

## 4. UI/UX weaknesses and opportunities

Write only the most prominent issues. For each item use:

`[High/Medium/Low] Title — evidence — why it matters — concrete improvement`

Do not label an automation failure or a guessed coordinate as a product UX defect.

## 5. Journey and coverage

| Step | Expected | Actual | Evidence | Status |
|---|---|---|---|---|
| Entry | | | screenshot or semantic ref | Confirmed / Observed / Unverified |
| Target page | | | screenshot or semantic ref | |
| Read-only checks | | | screenshot | |

Also state what was not tested: scrolling, tabs, deep links, buttons with side effects,
login/account state, or other out-of-scope areas.

For a long page, record coverage by screen: `首屏 / 中段 / 底部`. Do not describe
below-the-fold modules unless a fresh screenshot confirms them.

## 6. Risks and next steps

List purchase/order/claim/activation/account-changing controls that were intentionally
not clicked. End with the smallest next test that would increase coverage safely.

## 7. Evidence presentation

Place each useful screenshot next to the functional module or UX finding it supports;
do not put all evidence in a detached gallery at the end. The HTML exporter should
render these images as compact thumbnails and open the original image in a lightbox
on click.
