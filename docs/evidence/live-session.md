# Live session against Azure staging

Recorded 2026-10-05 05:20 UTC against `https://dp-staging-api.calmbush-9af7bb8b.eastus2.azurecontainerapps.io` (Azure Container Apps, eastus2) with the real Cosmos DB account behind it. Every response below is verbatim; the API key is sent as `X-API-Key` and not shown. Times are measured from the caller, so they include the network round trip (about 300 ms from where this was recorded); the server-side p95 for `/price` is under 25 ms (`PLAN.md`).

## Readiness: the policy and the catalogue it serves

```http
GET /ready   (no API key)
```

```text
200  (299 ms)
{"status":"ready","policy_version":"v1-thompson","products":50}
```

## A price for the best-selling product

```http
GET /price?user_id=evidence-1&product=85123A
```

```text
200  (3253 ms: the first request after the revision scaled from zero)
{"user_id":"evidence-1","product":"85123A","price":5.01,"impression_id":"i-9a517cb583c142b1a648b0b120aaac0c","policy_version":"v1-thompson"}
```

## The outcome of that impression

```http
POST /reward
{"id": "r-evidence-1791177660", "impression_id": "i-9a517cb583c142b1a648b0b120aaac0c", "converted": true, "margin": 0.95}
```

```text
200  (316 ms)
{"id":"r-evidence-1791177660","duplicate":false,"applied":true}
```

## The same reward again: a duplicate, the posterior does not move twice

```http
POST /reward
{"id": "r-evidence-1791177660", "impression_id": "i-9a517cb583c142b1a648b0b120aaac0c", "converted": true, "margin": 0.95}
```

```text
200  (305 ms)
{"id":"r-evidence-1791177660","duplicate":true,"applied":false}
```

## A reward for an impression that was never served

```http
POST /reward
{"id": "r-evidence-1791177660-x", "impression_id": "i-never-served", "converted": true, "margin": 1.0}
```

```text
404  (286 ms)
{"detail":"impression was never served"}
```

## A product outside the catalogue

```http
GET /price?user_id=evidence-1&product=NOPE
```

```text
404  (286 ms)
{"detail":"unknown product NOPE"}
```

## No API key: refused before pricing

```http
GET /price?user_id=evidence-1&product=85123A   (no API key)
```

```text
401  (289 ms)
{"detail":"invalid API key"}
```

## A body over 4 KB: refused before parsing

```http
POST /reward
<5,000 bytes>
```

```text
413  (288 ms)
{"detail":"payload too large"}
```

## 40 concurrent requests: the per-replica rate limit (20 rps, burst 20)

```text
status counts: {200: 35, 429: 5}
Retry-After on the 429s: ['1']
```

The `/metrics` block below was read before this burst.

## What `/metrics` counted

```text
dp_request_seconds_bucket{le="0.005",path="/price",status="200"} 0.0
dp_request_seconds_bucket{le="0.01",path="/price",status="200"} 0.0
dp_request_seconds_bucket{le="0.025",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="0.05",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="0.1",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="0.25",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="0.5",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="1.0",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="2.5",path="/price",status="200"} 30.0
dp_request_seconds_bucket{le="+Inf",path="/price",status="200"} 31.0
dp_rejected_total{reason="unauthorized"} 1.0
dp_rejected_total{reason="payload_too_large"} 1.0
dp_prices_served_total{policy_version="v1-thompson"} 31.0
dp_price_guard_clamped_total 0.0
dp_rewards_total{outcome="applied"} 1.0
dp_rewards_total{outcome="duplicate"} 1.0
dp_rewards_total{outcome="unknown_impression"} 1.0
```
