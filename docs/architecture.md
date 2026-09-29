# Architecture

## Request path

```
client ──▶ GET /price ──▶ ThompsonSampler ──▶ FeatureStore ──▶ Redis (online)
                              │
                              └──▶ response { user_id, price }
```

1. The API reads the customer's features from the online store (Redis).
2. The sampler draws one sample per price arm from its Beta posterior and picks
   the arm with the highest expectation.
3. The sampled price is clamped to `PRICE_MIN` / `PRICE_MAX` before it is returned.
4. The served arm is recorded so a later `POST /reward` can attribute the outcome.

## Learning loop

```
POST /reward (conversion, margin, LTV)
        │
        ▼
Cosmos DB (durable events) ──▶ scripts/retrain.py ──▶ MLflow (metrics + registry)
        ▲                                                     │
        └──────────── posterior recalibration ◀───────────────┘
```

- Online: Redis holds the current posterior parameters, so updates cost a single write.
- Durable: every served price and its outcome land in Cosmos DB, which is what the
  weekly retraining job replays.
- Retraining never mutates a registered model in place; it registers a new version.

## Stores

| Store | Role | Access pattern |
|---|---|---|
| Azure Cache for Redis | live posterior + hot features | point reads on the request path |
| Azure Cosmos DB | served arms, rewards, attributes | append-heavy writes, batch reads at retrain time |

## Failure behaviour

- **Redis unavailable** — the service falls back to the last known posterior in
  the local cache; if there is none, it returns the mid-point of the allowed
  range and marks the response as degraded.
- **Cosmos DB unavailable** — the response is still served; the event is buffered
  and flushed by the retraining job. Losing an event degrades learning, never
  serving.
- **No features for a customer** — fall back to the segment-level posterior.

## Deployment

The container runs on Azure Container Apps behind the platform ingress. Secrets
come from Key Vault through a managed identity; the image is built from
`docker/Dockerfile` and pushed to Azure Container Registry.
