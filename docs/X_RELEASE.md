# Release on X (Twitter) — with *your* account

This environment **cannot post as you** without your X login/API credentials  
(no `TWITTER_*` / X API keys found; GitHub profile has no linked `twitter_username`).

You post in ~60 seconds. Copy/paste below.

---

## Option A — Mobile / web (fastest)

1. Open https://x.com/compose/post while logged into **your** account  
2. Paste **Post 1** below  
3. Attach (optional):  
   - screenshot of `make demo` finishing, or  
   - `docs/assets/demo.gif` from the repo  
4. Post  
5. Immediately reply to yourself with **Post 2** (thread)  

### Post 1 (main)

```
Multi-agent pipelines die mid-run and lose work.

NEXUS Core checkpoints every step and resumes after a crash.
Judge checks real success criteria — not “the model said OK.”

make install && make demo

https://github.com/VincentMarquez/nexus-core
```

### Post 2 (thread reply)

```
Presence validator: agent returned JSON → “pass”
…even when the artifact is wrong.

Rubric judge: does the file meet success_criteria?

make demo-judge

MIT · feedback welcome
```

### Post 3 (optional, later same day)

```
If you run multi-agent jobs overnight:
this is the failure mode I kept hitting (kill mid-pipeline).

Open source core:
https://github.com/VincentMarquez/nexus-core
```

---

## Option B — X API (for automation later)

1. Developer portal: https://developer.x.com/  
2. Create a Project + App with **Read and Write**  
3. Create tokens (keep secret; never commit)  
4. Example with env vars only on your machine:

```bash
# DO NOT put real secrets in the repo
export X_API_KEY=...
export X_API_SECRET=...
export X_ACCESS_TOKEN=...
export X_ACCESS_SECRET=...
# then use any small CLI you trust, e.g. twurl / custom script
```

I can wire a **local-only** `scripts/post_x.py` that reads env vars if you add keys later — still never commit secrets.

---

## Best practices (2025–26 launch posts)

| Do | Don’t |
|----|--------|
| Lead with the **pain** | Lead with “please star” |
| One link | Five links + spam hashtags |
| Demo proof (`make demo`) | Vague “framework for agents” |
| Reply to every comment for hours | Post and disappear |
| Thread 2–3 short posts | 2000-character wall |
| Post when you’re free (US weekday morning often good for HN; evening OK for X) | Post and go offline |

---

## After you post

1. Pin the post on your profile for 48h  
2. Drop the same link once on LinkedIn (`SOCIAL_POSTS.md`)  
3. Show HN when free (`SHOW_HN.md`)  
4. Watch GitHub Insights → traffic  

Paste the X post URL here if you want the README updated with “As seen on …”
