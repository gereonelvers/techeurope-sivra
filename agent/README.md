# DOM Oracle — vision SFT dataset for the buyer agent

A **DOM oracle** that drives perfect computer-use buy trajectories over the
marketplace (`apps/marketplace/`, the 3 skins `site-a` / `site-b` / `site-c`)
and formats them as a vision SFT dataset for a Gemma-vision fine-tune.

The oracle is *privileged*: for each task it asks the marketplace for the
ground-truth target (the cheapest matching listing) via `POST /api/episode`,
drives a realistic buy path with Playwright, and records — **at each step,
before the action is executed** — a fixed 1280x800 screenshot plus the action
whose click coordinates are the **pixel center of the target element**
(`locator.bounding_box()` → `x+width/2, y+height/2`). After the run it calls
`GET /api/reward` and keeps the trajectory only if `success === true`.

## Layout

```
agent/
  README.md
  oracle/
    config.py          # paths, fixed viewport, action schema, FIXED system prompt,
                       # chromium executable resolution
    tasks.py           # sample valid {site, taskSpec} tasks from the seeded sqlite DB
    oracle.py          # the Playwright driver: one episode -> a recorded trajectory
    run.py             # ENTRYPOINT: sample tasks -> trajectories + images + stats
    build_dataset.py   # ENTRYPOINT: trajectories.jsonl -> sft.jsonl

data/datasets/buyer/   # (outputs; created by run.py / build_dataset.py)
    images/<episodeId>_<step>.png
    trajectories.jsonl
    sft.jsonl
    stats.json
```

## Prerequisites

Repo-root venv with Playwright + Pillow (httpx already present):

```bash
cd <repo-root>
.venv/bin/pip install playwright pillow
.venv/bin/python -m playwright install chromium
```

> Note: this project launches the **full Chromium build** with `--headless=new`
> (resolved by `config.chromium_executable()`), so it does **not** depend on the
> separate `chrome-headless-shell` download, which was flaky to fetch in this
> environment. If `chromium_executable()` returns `None`, Playwright's default
> resolution is used.

## Run the marketplace

The dataset is generated against a live marketplace on port 3000:

```bash
cd apps/marketplace
# DB already seeded (prisma/dev.db, 750 listings). If missing:
#   npx prisma db push && npm run seed
npm run build        # already passes
npm run start        # serves http://localhost:3000  (run in background)
# wait until http://localhost:3000/site-a returns 200
```

## Generate the dataset

```bash
cd agent/oracle

# 1) Smoke: 5 tasks across the 3 sites, prints every reward. Expect 5/5 success.
../../.venv/bin/python run.py --n 5 --seed 1 --smoke

# 2) Full run: aim for ~300-500 successful trajectories across 3 sites / 6 cats.
../../.venv/bin/python run.py --n 420 --seed 7

# 3) Build the vision SFT file from the kept trajectories.
../../.venv/bin/python build_dataset.py
```

`run.py` flags: `--n` tasks, `--seed`, `--smoke` (verbose rewards),
`--append` (append to `trajectories.jsonl` instead of truncating; skips
rewriting `stats.json`).

## The action schema (fixed; reused by the fine-tune)

One JSON action per step, viewport fixed at 1280x800, `deviceScaleFactor=1`:

```
{"action":"click","x":int,"y":int}   # x,y = pixel center of the target element
{"action":"type","text":str}         # type into the focused field
{"action":"scroll","dy":int}         # + = down
{"action":"navigate_back"}
{"action":"done","item_id":int}      # task complete; the purchased item
```

## The buy path the oracle drives

For each task (`config.MAX_STEPS = 25` cap, per-task exceptions are caught):

1. `POST /api/episode {site, taskSpec}` via the **browser context's** request
   API (so the `episode_id` cookie is shared with the pages) → `{episodeId,
   targetItemId}`.
2. `goto /<site>` → click + type the category into `[data-qm=search]` → submit
   via `[data-qm=search-submit]`.
3. Apply the category facet `[data-qm=facet-category-<Cat>]` + `[data-qm=apply-filters]`,
   then set `[data-qm=sort]` to **price ascending** + `[data-qm=sort-apply]`.
   Because the target *is* the cheapest match, price-ascending sort puts it
   first on page 1.
4. Reach + click `[data-qm=listing-<targetItemId>]` (scroll into view if needed;
   page-2 / direct-nav fallbacks exist so the path always reaches the target).
5. `[data-qm=add-to-cart]` → cart → `[data-qm=checkout]` → checkout form
   (fields are pre-filled with valid defaults) → `[data-qm=place-order]`.
6. Emit `{"action":"done","item_id":targetItemId}` (screenshots the confirmation).

## Output formats

`trajectories.jsonl` — one row per kept trajectory:

```json
{"episodeId": "...", "site": "site-a", "taskSpec": {...}, "targetItemId": 223,
 "reward": {"success": true, "attrMatch": 1, ...},
 "steps": [{"step": 0, "image": "<abs png path>", "action": {...}}, ...]}
```

`sft.jsonl` — one row per (screenshot, action) **step**, chat-vision format for
Unsloth/Gemma. The system prompt (`config.SYSTEM_PROMPT`) is **identical across
every row** (we are deliberately overfitting):

```json
{"messages":[
  {"role":"system","content":"<fixed buyer-agent + action-schema prompt>"},
  {"role":"user","content":[
     {"type":"image","image":"<abs path to png>"},
     {"type":"text","text":"Goal: <task as one line>. Output the next action as JSON."}]},
  {"role":"assistant","content":"<action json>"}]}
```

(The final `done` step has no screenshot, so its user turn is text-only.)

`stats.json` — tasks attempted, trajectories kept, success rate, per-site and
per-category counts, total steps, mean steps/trajectory.
