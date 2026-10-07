# Randomised price test on Azure

Run on 2026-10-07 against the API deployed on Azure Container Apps with
`EXPERIMENT_SHARE=1`, Cosmos DB behind it, then exported and analysed. The stack was
destroyed afterwards.

## What was tested

The fitted elasticities come from prices the retailer chose, so they are biased. A
randomised price test removes that bias: each customer gets one of a product's five
prices at random, with a known probability (1/5), and the slope of purchase rate on price
is then causal.

There is no store behind this project, so the customers were simulated by `dp.shoppers`.
Each shopper asked the deployed API for a price and bought with the probability of a
**hidden** demand curve whose elasticity is the observational one times 0.6: less
price-sensitive, as it would be if the retailer's prices had moved with demand. The test
passes if `dp.experiment` recovers the hidden elasticity, not the observational one.
Everything else is the production path: random assignment and propensities in the API, the
impressions and rewards in Cosmos DB, `dp.export` reading them with the operator's Azure
CLI login (keys are disabled), and the analysis.

## The run

| | |
|---|---|
| Deployed image | `ghcr.io/juandsep/dynamic-pricing-engine:dev`, `EXPERIMENT_SHARE=1` |
| Products | the 10 best sellers |
| Shoppers | 20,556 impressions (about 2,056 per product), 2,745 purchases |
| Assignment | every impression `v0-uniform`, propensity 0.2; 375 to 456 impressions per (product, price) |
| Duration | 17:33 to 18:09 UTC at about 15 requests per second; no 429, no 5xx |
| Interruption | the first batch stopped after 9,556 shoppers when one connection timed out on the client; fixed in #40 and resumed with new shopper ids |

## Result

Elasticity per product. The estimate is a binomial GLM with a log link, ± one standard
error. *z vs hidden* is how many standard errors the estimate sits from the hidden truth;
*observational off by* is how far the observational value sits from the estimate.

| Product | Observational | Hidden (truth) | Estimated from the test | z vs hidden | Observational off by (SE) | Requests |
|---|---|---|---|---|---|---|
| 84077 | -4.37 | -2.62 | -2.44 ± 0.14 | +1.36 | -14.1 | 2,056 |
| 85099B | -2.94 | -1.76 | -1.83 ± 0.19 | -0.37 | -6.0 | 2,056 |
| 85123A | -3.86 | -2.32 | -2.75 ± 0.18 | -2.36 | -6.0 | 2,057 |
| 22197 | -2.36 | -1.41 | -1.34 ± 0.16 | +0.48 | -6.3 | 2,056 |
| 84879 | -1.87 | -1.12 | -0.92 ± 0.18 | +1.16 | -5.4 | 2,056 |
| 21212 | -2.10 | -1.26 | -1.41 ± 0.11 | -1.32 | -6.1 | 2,056 |
| 17003 | -4.25 | -2.55 | -2.64 ± 0.13 | -0.70 | -12.7 | 2,054 |
| 21977 | -2.91 | -1.75 | -1.87 ± 0.12 | -1.07 | -8.6 | 2,055 |
| 84991 | -2.66 | -1.60 | -1.69 ± 0.12 | -0.82 | -8.2 | 2,055 |
| 15036 | -2.40 | -1.44 | -1.35 ± 0.13 | +0.69 | -8.0 | 2,055 |

- **9 of 10 estimates fall within two standard errors of the hidden truth**, about what
  honest standard errors give (95%). The tenth, 85123A, is 2.4 standard errors out.
- **The observational elasticity is rejected for every product**: it sits 5.4 to 14.1
  standard errors from what the test measured. The test sees the bias the historical
  data cannot.
- The median standard error is 0.13 at about 2,000 requests per product. These shoppers
  buy more often than the simulator's 5% (20% at the median price), which is why the test
  needed fewer requests than `dp.experiment` projects for the simulated log.

Reproduce: `terraform apply -var experiment_share=1`, then
`API_KEY=... python -m dp.shoppers <url> --products 10 --requests 2000`,
`COSMOS_ENDPOINT=... python -m dp.export events.jsonl`, and
`python -m dp.experiment --events events.jsonl --truth data/processed/shopper_truth.json`.
