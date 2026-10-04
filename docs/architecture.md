# Architecture

## Request path

```
caller ──▶ GET /price ──▶ API key, rate limit ──▶ ThompsonSampler ──▶ Store ──▶ Cosmos DB
  (server)                                            │                     posteriors, events
                                                      └──▶ { price, impression_id, policy_version }
```

1. The caller (a checkout or order server, with `X-API-Key`) names a user and a product.
2. The API reads the product's posterior: one document, a Beta per arm.
3. The sampler draws a conversion rate per arm, multiplies it by the arm's unit margin and
   serves the highest. The share of 1,000 draws that pick the served arm is its propensity.
4. The price is clamped to `PRICE_MIN` / `PRICE_MAX`; a clamp is counted in `/metrics`.
5. The impression (price, arm index, propensity, policy version) is appended to `events`, so a
   later `POST /reward` can attribute the outcome.

## Learning loop

```
online   POST /reward ──▶ claim reward id in events ──▶ incr alpha or beta in posteriors
offline  UCI data ──▶ dp.data ──▶ dp.demand ──▶ dp.retrain ──▶ MLflow (runs, registry)
                                                    └──▶ catalogue.json (in the image)
```

- Online: every reward is one atomic `incr` patch on the product's posterior document, so the
  policy learns from each outcome as it arrives and a restart does not forget.
- Offline: retraining rebuilds the catalogue (arms, unit cost) and the reference profile from
  the data and registers them as a new immutable version; nothing is overwritten.

```json
// ponytail: retraining reads the fitted curves, not the events in Cosmos. Replay the
// `events` container into the posterior (the late rewards the window excluded) once the
// service has real traffic worth learning from offline.
```

## Stores

| Store | Role | Access pattern |
|---|---|---|
| Azure Cosmos DB, `posteriors` | one document per product, a Beta per arm | point read per price, atomic patch per reward |
| Azure Cosmos DB, `events` | impressions and rewards (`docs/data-contract.md`) | append per price and per reward, point read to attribute a reward |

One store, two workloads. The online document set is tiny — one document per product, on the
order of tens of KB — and a Cosmos point read is a single-digit-millisecond operation, so a separate
cache in front of it buys latency the request path does not need.

```json
// ponytail: one Cosmos account and one replica. Add Azure Cache for Redis (~20 USD/month) only
// when replicas > 1 makes the shared document set a contention point, or when the point read
// measurably misses the 50 ms p95 budget.
```

## Failure behaviour

- **Cosmos DB unavailable, request path** — the sampler serves from the uniform prior: the
  customer still gets a price inside the product's band, the policy explores instead of
  exploiting, and the lost impression only costs one log row.
- **Cosmos DB unavailable, reward path** — `POST /reward` answers **503** instead of accepting
  an outcome it cannot persist. The reward id is claimed with an atomic create before the
  posterior moves, and the claim is removed if the update fails, so the client's retry is safe
  and never applied twice. Dropping the reward silently would corrupt learning while leaving
  the service looking healthy.
- **No catalogue** — `/ready` answers 503, so the platform holds traffic.
- Losing an event degrades learning, never serving.

## Deployment

The container runs on Azure Container Apps behind the platform ingress: 0.25 vCPU, 0.5 GiB,
zero to one replica, liveness on `/health` and readiness on `/ready`. Scaled to zero, it bills
nothing; the environment has no Log Analytics workspace, so nothing is ingested between demos.
The image is built from `docker/Dockerfile` and published to **GHCR** as a public package, which the
Container App pulls anonymously — no registry credentials, no token to rotate. No cloud credential
exists: the app authenticates to Cosmos DB with its managed identity plus a data-plane role
assignment, and CI authenticates to Azure with OIDC federated credentials. The one secret is the
API key callers present, held as a Container Apps secret (free) and never in the repository.
