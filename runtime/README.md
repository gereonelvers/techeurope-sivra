# runtime — LIVE buyer-agent path

Serves the buyer-agent **Gemma 4 vision** policy on Modal and drives the live
marketplace (`http://localhost:3000`) with it via a Playwright observe→act loop,
plus a parallel fleet runner whose state feeds the `mission_control` dashboard.

This dir is self-contained: its own venv at `runtime/.venv` (playwright, modal,
httpx, pillow, fastapi, uvicorn). It only **reads** `vision_ft/` and `agent/` — it
never modifies them. The heavy ML deps (transformers/peft/torch/torchvision) live
**only inside the Modal image**, never in the local venv.

```
runtime/
├── serve_modal.py   # Modal serving app (NEW app `buyer-vision-serve`): loads
│                    #   google/gemma-4-E2B-it + LoRA from volume buyer-vision-ckpt:/adapter
│                    #   (if present, else base) -> next-action JSON. Warm container.
├── agent_loop.py    # one episode: POST /api/episode -> screenshot -> serve -> parse
│                    #   action -> execute in Playwright -> GET /api/reward. Robust.
├── fleet.py         # N concurrent agents (asyncio + 1 BrowserContext each), each its
│                    #   own episode; streams mission_control-shaped state + /api/fleet.
├── README.md
└── .venv/           # playwright + modal + httpx + pillow + fastapi + uvicorn
```

## Contract with the training job
`serve_modal.py` reuses the EXACT prompt the fine-tune was trained on
(mirrors `vision_ft/build_dataset.py`): the system prompt, the
`GOAL: Find and purchase the best matching item for: <goal>.` user turn, and the
goal string format `category=Phones, brand=OnePlus | site=site-a`. Action schema
(viewport 1280×800):

```
{"action":"click","x":int,"y":int}
{"action":"type","text":str}
{"action":"scroll","dy":int}
{"action":"navigate_back"}
{"action":"done","item_id":int}
```

Decoding is greedy (`do_sample=False`, temp 0). Output is parsed/clamped to the
schema; an unparseable reply degrades to a no-op scroll so the loop never crashes.

## 1. Serving (Modal)

```bash
cd runtime
set -a; source ../.env; set +a            # MODAL_TOKEN_ID / MODAL_TOKEN_SECRET

# In-container smoke (loads gemma4 on an A100, infers on one real screenshot):
.venv/bin/modal run serve_modal.py

# Deploy the warm HTTP endpoint:
.venv/bin/modal deploy serve_modal.py
# -> POST https://<workspace>--buyer-vision-serve-infer.modal.run
#    body  {"image_b64": "<base64 png>", "goal": "<goal text>"}
#    reply {"action": {...}, "raw": "...", "adapter_loaded": bool, "gpu": str}
```

The container keeps `min_containers=1` warm so the fleet isn't cold per call.

### Re-point serving at the trained adapter
**Nothing in the code changes.** The endpoint reads the volume on container
start: if `buyer-vision-ckpt:/adapter/adapter_config.json` exists, it loads +
merges the LoRA; otherwise it serves base. Once `vision_ft`'s `full_train`
commits the adapter to the volume, just bounce the app so a fresh container
re-reads the volume:

```bash
.venv/bin/modal deploy serve_modal.py        # redeploy -> new warm container picks up /adapter
# (or) .venv/bin/modal app stop buyer-vision-serve   # drop warm containers; next call reloads
```

Confirm it took: the `infer` response field `"adapter_loaded": true`.

## 2. Single-episode runtime

```bash
cd runtime
set -a; source ../.env; set +a
.venv/bin/python agent_loop.py \
    --endpoint https://<workspace>--buyer-vision-serve-infer.modal.run \
    --site site-a --category Phones --brand OnePlus
```

Prints the per-step actions and the final reward.

## 3. Fleet at scale

```bash
cd runtime
set -a; source ../.env; set +a
.venv/bin/python fleet.py \
    --endpoint https://<workspace>--buyer-vision-serve-infer.modal.run \
    --n 100 \
    --serve-port 8900 \
    --state-file /tmp/fleet_state.jsonl
```

- `--n` concurrent agents, each its own Playwright `BrowserContext` + episode,
  tasks sampled via `agent/oracle/tasks.py` (satisfiable {site, taskSpec}).
- `--serve-port` exposes `GET /api/fleet?n=N` returning
  `{"agents":[...],"stats":{...}}` in the shape `mission_control` consumes. Point
  the dashboard at it: run `mission_control` with
  `FLEET_UPSTREAM=http://localhost:8900`.
- `--state-file` also appends a compact per-step JSONL snapshot.

Per-agent record shape (mission_control-compatible):
```json
{"agent_id":"buyer-000","site":"site-a","screenshot_url":"data:image/png;base64,...",
 "action":{"action":"click","x":590,"y":31},"goal":"category=Phones | site=site-a",
 "category":"Phones","status":"running","step":3,"n_steps":20,"reward":null}
```

## Status (base model, adapter still training)
The base `google/gemma-4-E2B-it` is **not** trained on this task, so its actions
are not accurate — the value here is that the **plumbing is proven end-to-end**:
gemma4 vision loads on a Modal A100, returns a schema-valid action for a real
screenshot, and the observe→act→reward loop and the fleet run without errors.
Accuracy lands when `buyer-vision-ckpt:/adapter` appears and the endpoint is
bounced (see "Re-point serving at the trained adapter").
