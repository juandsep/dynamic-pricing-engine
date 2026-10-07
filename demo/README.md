---
title: Dynamic Pricing Demo
sdk: static
app_file: index.html
pinned: false
---

# Dynamic pricing demo

A one-page explanation of the dynamic pricing engine for someone who has not read the code:
the problem, how it works, the learning curve of Thompson Sampling against the usual price
and a random price, the margin each policy earned on the top 50 products of UCI Online
Retail II, a per-product explorer, the assumptions behind the numbers, and how the same
policy runs on Azure.

The page is plain HTML and JavaScript over `data.json` (12 KB), written by `make_data.py`
from the simulator: per product, the arms, the expected margin at each one, where Thompson
Sampling sent the traffic and when it settled; and the learning curve of every policy at
48 log-spaced checkpoints. It calls no API and needs no credentials, so it costs nothing to
host. Light and dark follow the viewer's system setting.

## Run locally

```bash
python -m http.server -d demo 8000   # then open http://localhost:8000
```

## Refresh the data and publish

After `python -m dp.demand`:

```bash
uv run python demo/make_data.py
hf upload <user>/dynamic-pricing-demo demo . --type space --exclude make_data.py
```

A static Space, like the reference project's: Hugging Face hosts those free.
