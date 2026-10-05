# Diagrams

Every box and arrow below maps to code or Terraform in this repository. The module diagram is
generated from the graphify code graph (`graphify update .` builds it into `graphify-out/`, which
is git-ignored): its import edges were read from the graph and checked against the source.

## Deployment on Azure

```mermaid
flowchart LR
    caller["Caller<br/>checkout or order server"]
    subgraph gh["GitHub"]
        ci["ci.yml<br/>lint, tests, image build"]
        deploy["deploy.yml<br/>image to GHCR, OIDC deploy"]
        ghcr[("GHCR<br/>public image")]
    end
    subgraph az["Azure subscription, rg-dp-staging, eastus2"]
        subgraph env["Container Apps environment, no Log Analytics"]
            app["dp-staging-api<br/>FastAPI, 0.25 vCPU, 0 to 1 replica"]
        end
        subgraph cosmos["Cosmos DB, free tier, keys disabled"]
            post[("posteriors")]
            events[("events")]
        end
        entra["Entra ID<br/>federated credentials"]
    end
    hf["Hugging Face Space<br/>static demo"]

    caller -- "X-API-Key" --> app
    app -- "managed identity<br/>Data Contributor" --> post
    app -- "managed identity" --> events
    deploy -- "push" --> ghcr
    ghcr -- "anonymous pull" --> app
    deploy -- "OIDC token" --> entra
    deploy -- "az containerapp update<br/>Contributor on the RG" --> app
```

## Request path

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant A as API (api.py)
    participant T as ThompsonSampler
    participant S as Store (Cosmos)
    C->>A: GET /price?user_id&product, X-API-Key
    A->>A: key check, token bucket (429), size limit (413)
    A->>T: quote(product)
    T->>S: posterior(product)
    S-->>T: alpha, beta per arm (prior if Cosmos is down)
    T->>T: 1,000 Beta draws x unit margin, argmax, propensity
    T-->>A: price, arm, propensity
    A->>S: record_event(impression)
    A-->>C: price, impression_id, policy_version
    C->>A: POST /reward {id, impression_id, converted, margin}
    A->>S: event(impression_id)
    A->>S: claim(reward)  atomic create, duplicate stops here
    A->>S: add_outcome  atomic incr on alpha or beta
    A-->>C: applied, or 503 with the claim rolled back
```

## Training pipeline

```mermaid
flowchart LR
    uci[("UCI Online Retail II<br/>44 MB workbook")] --> data["dp.data<br/>DuckDB ingest and cleaning"]
    data --> orders[("orders.parquet<br/>955,850 lines")]
    orders --> demand["dp.demand<br/>log-log curve per product"]
    demand --> curves[("demand_curves.parquet<br/>2,759 curves")]
    curves --> sim["dp.simulate<br/>oracle, modal, uniform, Thompson"]
    sim --> log[("simulated log<br/>known propensities")]
    sim --> retrain["dp.retrain"]
    retrain --> mlflow[("MLflow<br/>runs and registry")]
    retrain --> cat[("catalogue.json<br/>+ reference profile")]
    cat --> image["API image"]
    log --> drift["dp.drift<br/>PSI vs reference"]
    cat --> drift
```

## Module dependencies (from the code graph)

An arrow means "imports from". Read from the `imports_from` edges graphify extracted, which the
graph marks `EXTRACTED` (taken from the AST, not inferred).

```mermaid
flowchart TD
    api["api.py<br/>/price, /reward, /ready, /metrics"]
    thompson["thompson.py<br/>sampler, catalogue"]
    store["store.py<br/>Cosmos or in-memory"]
    simulate["simulate.py<br/>world, policies, log, replay"]
    retrain["retrain.py<br/>MLflow run and registry"]
    drift["drift.py<br/>PSI"]
    demand["demand.py<br/>price curves"]
    data["data.py<br/>DuckDB ingest"]

    api --> thompson
    api --> store
    thompson --> store
    simulate --> thompson
    simulate --> demand
    simulate --> data
    demand --> data
    retrain --> simulate
    retrain --> demand
    retrain --> data
    retrain --> thompson
    retrain --> drift
    drift --> simulate
```

The serving side (`api`, `thompson`, `store`) imports nothing from the pipeline side, which is
what lets the image leave out DuckDB, pandas and MLflow (383 MB instead of 1.42 GB).

What the graph says about the code as a whole (443 nodes, 850 edges, 21 communities, no import
cycles): the most connected abstractions are `Store` (22 edges), `load_events()` (17),
`get_sampler()` (15) and `retrain.run()` (15).

## Delivery

```mermaid
flowchart LR
    branch["feat/ fix/ chore/ docs/"] -- "PR, ci.yml green" --> dev["dev"]
    dev -- "push" --> img1["image :sha and :dev to GHCR"]
    img1 --> roll["OIDC login, az containerapp update,<br/>smoke test on /ready"]
    dev -- "release PR" --> main["main"]
    main -- "push" --> img2["image :main, no deploy"]
    manual["workflow_dispatch"] --> retrain["retrain.yml<br/>ingest, fit, simulate, register on DagsHub"]
```
