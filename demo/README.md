---
title: Dynamic Pricing Demo
sdk: static
app_file: index.html
pinned: false
---

# Dynamic pricing demo

How four pricing policies do on the top 50 products of UCI Online Retail II, and, for
one product, what each of its five prices earns against where Thompson Sampling sent
the traffic.

The page is plain HTML and JavaScript over `data.json` (8 KB): per product, the arms,
the expected margin per request at each one, the share of requests Thompson Sampling
served to each, and which arm is best and which is the retailer's usual price. It
calls no API and needs no credentials, so it costs nothing to host.

The numbers come from the simulator: price-response curves fitted on the real data,
cost at half the modal price, 5% conversion at the median price. The elasticities
are an upper bound (prices were not randomised), so this is a known world to test the
policy on, not a claim about the retailer.

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
