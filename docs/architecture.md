# Architecture

## Request path

```
client ──▶ GET /price ──▶ ThompsonSampler ──▶ Store ──▶ Cosmos DB (posterior, events)
                              │
                              └──▶ response { user_id, price }
```

1. The API reads the current posterior for the product (the segment) from the store.
2. The sampler draws one sample per price arm from its Beta posterior and picks
   the arm with the highest expectation.
3. The sampled price is clamped to `PRICE_MIN` / `PRICE_MAX` before it is returned.
4. The served arm is recorded so a later `POST /reward` can attribute the outcome.

## Learning loop

```
POST /reward (conversion, margin, LTV)
        │
        ▼
Cosmos DB (posterior + durable events) ──▶ python -m dp.retrain ──▶ MLflow (metrics + registry)
        ▲                                                             │
        └──────────── posterior recalibration ◀───────────────────────┘
```

- Online: the current posterior parameters live in Cosmos DB (container `posteriors`) as
  one document per product with its arms inside, so a reward update is a single atomic
  `incr` patch and every replica reads the same document.
- Durable: every served price and its outcome land in the same account, and are what the
  weekly retraining job replays.
- Retraining never mutates a registered model in place; it registers a new version.

## Stores

| Store | Role | Access pattern |
|---|---|---|
| Azure Cosmos DB | live posterior, hot features, served arms, rewards | point reads on the request path, append-heavy writes for events, batch reads at retrain time |

One store, two workloads. The online document set is tiny — one document per product, on the
order of tens of KB — and a Cosmos point read is a single-digit-millisecond operation, so a separate
cache in front of it buys latency the request path does not need.

```json
// ponytail: one Cosmos account and one replica. Add Azure Cache for Redis (~20 USD/month) only
// when replicas > 1 makes the shared document set a contention point, or when the point read
// measurably misses the 50 ms p95 budget.
```

## Failure behaviour

- **Cosmos DB unavailable, request path** — the service serves from the last known posterior held in
  process memory and marks the response as degraded. With one replica, that cache is never stale
  relative to another instance.
- **Cosmos DB unavailable, reward path** — `POST /reward` returns **503** instead of accepting an
  outcome it cannot persist. The idempotency key makes the client's retry safe. Dropping the reward
  silently would corrupt the posterior while leaving the service looking healthy.
- **No features for a customer** — fall back to the segment-level posterior.
- Losing an event degrades learning, never serving.

## Deployment

The container runs on Azure Container Apps behind the platform ingress, scaled to zero when idle.
The image is built from `docker/Dockerfile` and published to **GHCR** as a public package, which the
Container App pulls anonymously — no registry credentials, no token to rotate. Secrets are not used
at all: the app authenticates to Cosmos DB with its managed identity plus a data-plane role
assignment, and CI authenticates to Azure with OIDC federated credentials.
