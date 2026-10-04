# Next-agent prompt — Dynamic Pricing Engine

Copia todo lo que hay bajo la línea en el primer mensaje del agente siguiente.

Este fichero se borra en la fase F9: el prompt debe morir con la migración. El orden de trabajo
vigente es `PLAN.md`; donde los dos se contradigan, gana `PLAN.md`.

Va en español a propósito: los prompts de handoff son la única excepción a la regla de que todo el
contenido del repositorio está en inglés. No lo traduzcas.

---

CONTEXTO

- Repositorio: `juandsep/dynamic-pricing-engine` (la carpeta local tiene el mismo nombre).
  Trabaja solo dentro de esa carpeta.
- Proyecto Python con **uv** (`pyproject.toml` + `uv.lock`). Script de consola: `uv run dp`.
- Ramas: `main` (releases) ← `dev` (integración) ← ramas de trabajo cortadas de `dev`.
  Corta siempre de `dev`; `main` solo recibe PRs desde `dev`. Una preocupación por rama y PR.
- Fuente de verdad del plan: `PLAN.md` (bloque `## Status` + fases F1–F9 con su criterio de
  cierre). `README.md`, `PLAN.md`, `docs/architecture.md` e `infra/README.md` describen el estado
  **objetivo** y las decisiones ya tomadas: reconcilia, pero no re-abras esas decisiones.
- Referente de estructura y convenciones: `uplift-modeling-pipeline`, proyecto hermano en el mismo
  portfolio (GCP: espeja sus *convenciones*, nunca sus providers). Publica un `deploy.yml` aparte,
  no un job de deploy dentro de `ci.yml`.

ESTADO ACTUAL (mergeado en `dev`, HEAD `8bf5b31`)

- F0 (fundaciones), F0.5 (contrato de datos + replay offline) y F1 (ingesta + modelo de demanda).
  24 tests en verde, ruff limpio, CI verde.
- Existe: `scripts/fetch_data.sh`, `src/dp/data.py` (ingesta DuckDB de las dos hojas a Parquet),
  `src/dp/demand.py` (curvas de precio por producto, medidas fuera de muestra), `src/dp/simulate.py`
  (replay de un log), FastAPI `GET /price` y `/health`, `docs/data-contract.md`, `docs/architecture.md`,
  `docker/Dockerfile` (multi-stage, non-root, `PORT=8000`), `scripts/retrain.py`, `infra/README.md`
  con el bootstrap manual, `.github/workflows/ci.yml` (test + docker, acciones pinneadas a SHA).
- Siguen siendo stubs: `src/dp/thompson.py` (sortea uniforme dentro de `PRICE_MIN`/`PRICE_MAX`) y
  `FeatureStore.record_event` (lanza `NotImplementedError`). `redis` sigue declarado y en uso en
  `store.py`; `boto3` y `feast` ya se eliminaron en F1.
- **La data no viaja con el repo** (`data/` está en `.gitignore`). Regenerar y verificar
  reproducción antes de tocar nada:

      scripts/fetch_data.sh          # 44 MB → data/raw/ (si el fichero está, se salta)
      uv run python -m dp.data       # 9s  → data/processed/orders.parquet
      uv run python -m dp.demand     # 3s  → data/processed/demand_curves.parquet + demand_summary.json

  Números que debe reproducir (si no salen, para y averigua por qué antes de seguir): 955.850
  líneas limpias, 4.866 productos, panel de 126.354 observaciones, 2.759 curvas ajustadas (1.889
  descartadas por un solo precio, 218 por pocas observaciones), elasticidad mediana −2,41, R²
  mediano 0,53 dentro de muestra y 0,26 fuera (corte 2011-05-01), pooled −2,26, por tramo de precio
  −2,27 / −2,30 / −2,31 / −2,14.

HALLAZGOS DE F1 QUE CONDICIONAN LO QUE VIENE

- El segmento con información es el **producto**, no su tramo de precio: la elasticidad salió plana
  entre tramos (0,17 de recorrido).
- El R² fuera de muestra es la mitad que el de dentro: la curva aguanta en dos de cada tres
  productos y se degrada en el resto. No asumas curva estable en todo el catálogo.
- Los precios son observacionales (se movieron por stock y temporada, no al azar): las magnitudes
  son cota superior de la elasticidad causal. El simulador las usa como prior a explorar, nunca
  como verdad.
- No hay propensiones en la data: la evaluación off-policy requiere simular el log (F2).

SIGUIENTE PASO — F2, rama `feat/simulator`

1. Generador en `src/dp/simulate.py`: muestrea demanda desde el ajuste de F1, registra el brazo
   servido **con su propensión** y emite un log en el formato de `docs/data-contract.md`.
2. Rejugar sobre el mismo log cuatro políticas: mejor precio fijo (oráculo), precio modal,
   uniforme y Thompson Sampling.
3. Salida: regret contra el oráculo, margen acumulado, % del oráculo y cuántas peticiones necesitó
   cada brazo hasta que el posterior se asentó.

Dos decisiones a cerrar aquí y dejar escritas:

- Los brazos son **precios absolutos** dentro de la banda real de cada producto (la curva trae
  `median_price`), no un 1–100 global: con un arm genérico el regret no significa nada.
- El posterior es **por producto con los brazos dentro** (≈2.759 documentos), no por
  (brazo × segmento de precio) (≈52.000). Para la demo se puede limitar a los 50 productos con más
  unidades.

Criterio de cierre: en un log simulado con óptimo conocido, el oráculo gana por construcción y
Thompson converge a él dentro del presupuesto muestral. Ese assert es la fase; un test que solo
compruebe que el fichero se generó no la cierra.

DESPUÉS (detalle en `PLAN.md`)

- F3 `feat/thompson-policy` — Thompson real (Beta por brazo, argmax, clamp), posterior persistido,
  `record_event` contra Cosmos con `DefaultAzureCredential`, fuera Redis.
- F4 `feat/mlflow-and-reward` — un run padre por ejecución y un hijo por política en MLflow, la
  SHA-256 de la tabla de features como parámetro, registrar solo la mejor; `POST /reward`
  idempotente por request id, 4xx si el brazo nunca se sirvió, **503** si no se puede persistir;
  `GET /ready` con la versión de política servida.
- F5 `feat/serving-contract` — límites de tamaño de petición, rate limit por instancia (429),
  versión de política en la respuesta, contador de violaciones de suelo/techo de precio como métrica.
- F6 `feat/azure-infrastructure` — Terraform `azurerm`: resource group, Container Apps environment
  y app (ingress target port **8000**, min replicas 0), Cosmos NoSQL provisioned 1000 RU/s con free
  tier activado, managed identity + asignación de rol de data plane, Log Analytics/App Insights
  opcionales.
- F7 `feat/cicd-azure-deploy` — `deploy.yml` separado de `ci.yml` (push a `dev` → imagen a GHCR con
  el `GITHUB_TOKEN` → `az containerapp update`), `permissions: id-token: write`, grupo de
  `concurrency`, `environment: staging`, preflight que falla en voz alta si una variable está vacía,
  acciones pinneadas a SHA; `retrain.yml` con cron semanal y `workflow_dispatch`.
- F8 `feat/monitoring-demo` — PSI sobre la mezcla de tráfico y la distribución de precios servidos,
  contra un `reference_profile.json` guardado junto a la política registrada; demo estática.
- F9 `docs/azure-reality` — reconciliar `README.md`, `PLAN.md`, `docs/architecture.md` e
  `infra/README.md` con lo implementado, rellenar la tabla *Results* con números reales y **borrar
  este fichero**.

DECISIONES DE STACK (cerradas; no las re-abras sin precio actual de la API de precios de Azure)

- Compute: **Azure Container Apps**, consumo, min replicas 0. Grant: 180.000 vCPU-s, 360.000 GiB-s
  y 2M peticiones por suscripción y mes. Una revisión escalada a cero no factura.
- Región: **`eastus2`** (ACA factura 2,4e-05 USD/vCPU-s y 3e-06/GiB-s; `spaincentral` y `westeurope`
  3,4e-05 y 4e-06, ~42 % más).
- Imágenes: **GHCR**, paquete público, pull anónimo. ACR Basic son 0,1666 USD/día (~5,03 USD/mes)
  y factura aunque no haya nada desplegado.
- Store: **Cosmos DB NoSQL provisioned 1000 RU/s con free tier activado al crear** — 1000 RU/s y
  25 GB gratis de por vida, una cuenta por suscripción. **El free tier no aplica a serverless.**
- **Sin Redis**: Azure Cache for Redis C0 son 0,0275 USD/h (~20 USD/mes) para un solo réplica, donde
  el documento de posterior en Cosmos es equivalente. `docs/architecture.md` lleva el marcador
  `ponytail:` con la vía de escape.
- **Sin Key Vault y sin secretos**: managed identity + RBAC de data plane; CI por **OIDC federado**.
- Tracking: **MLflow alojado gratis en DagsHub**. Self-hosted necesita backend siempre encendido
  (~15-20 USD/mes).
- Todo **efímero**: `terraform apply` antes de una demo, `terraform destroy` después. El state se
  queda local (`infra/*.tfstate` ignorado).
- **Presupuesto: 10 USD/mes por suscripción con avisos al 50 %, 90 % y 100 %** (ya creado, vía REST,
  fuera de Terraform). Es un aviso, no un corte: una factura distinta de cero significa un recurso
  que sobrevivió a su demo.
- No añadas un recurso cuyo coste se discuta en el PR. Si crees que algún rechazo de arriba es
  erróneo, dilo con el precio actual de la API y que decida la persona.

QUÉ HACE FALTA DEL USUARIO (acciones sobre su suscripción, el agente no puede hacerlas)

- F2–F5: nada. Todo corre en local, sin cloud y sin gastar.
- F6–F7: `brew install azure-cli && az login && az account show`, y los pasos de `infra/README.md`:
  providers, RG `rg-dp-staging` en `eastus2`, **dos** federated credentials (`repo:juandsep/dynamic-pricing-engine:ref:refs/heads/dev`
  y `...:environment:staging`), rol Contributor acotado al RG, y los 3 secrets en GitHub:
  `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
- Esta máquina **no tiene `az`**: `terraform plan`/`apply` y `az containerapp update` no se pueden
  ejercitar en local. Dilo claramente en vez de reportar un plan que nunca corrió.
- F8: cuenta de Hugging Face si se quiere demo pública.

TRAMPAS YA PISADAS (no repetirlas)

- `read_xlsx` de DuckDB: tipos mezclados dentro de una columna (muere en la celda `A143`) →
  `all_varchar = true` y cast en SQL. No existe el parámetro `columns`. Con `all_varchar` las fechas
  llegan como **serial de Excel** (`1899-12-30 + serial·86400`).
- `WITH` dentro de una rama de `UNION ALL` es SQL inválido; `CREATE TABLE AS WITH ...` también.
- `StockCode` mezcla productos con `DOT`, `POST`, `M`, `ADJUST`, `AMAZONFEE`; `DOT` aparece con
  1.290 "precios". Filtro `^\d{5}[A-Za-z]{0,3}$`.
- UCI estrangula descargas repetidas (~11 KB/s frente a segundos la primera vez): el fichero se
  cachea en `data/raw/`.
- Skill `duckdb-data-ingest` con el detalle de todo esto; cárgala antes de tocar la ingesta.

REGLAS

- Todo el contenido del repositorio en **inglés** (código, comentarios, docs, commits). Las
  respuestas del chat, en español.
- Conventional Commits en imperativo. Una preocupación por rama y por PR.
- **Ningún recurso de Azure puede llevar un cargo mensual fijo.** Todo free tier, dentro de un
  grant, o destruido cuando no se usa. Un PR que introduzca una partida fija se rechaza aunque sea
  técnicamente correcto.
- Sin secretos en el repositorio y sin claves de cloud en CI: managed identity, RBAC de data plane,
  OIDC. Nunca push directo a `main`.
- Tests 100 % offline: la suite entera pasa sin credenciales de Azure. La integración con Cosmos se
  escribe diferida y fail-open, sin llamada de red al importar.
- Antes de cada commit: `uv run ruff check . && uv run ruff format .` y los 10 hooks de pre-commit.
- Toda afirmación de "verde" en el reporte sale de un comando que se ejecutó de verdad, con su
  salida real. Nada de resultados inventados.

CRITERIOS DE ACEPTACIÓN DEL PROYECTO

- `uv run pytest -q`, `uv run ruff check .` y `uv run ruff format --check .` pasan, y la imagen
  Docker construye — sin credenciales de Azure y sin servicio cloud alcanzable.
- `terraform validate` pasa para la configuración de Azure (después de `terraform init`).
- CI publica la imagen en GHCR y actualiza el Container App en `dev`, autenticado por OIDC.
- Ningún recurso en `infra/` tiene coste mensual fijo, y ningún fichero del repositorio provisiona
  Redis, ACR, Key Vault, Cosmos serverless ni un backend MLflow self-hosted.
- Ningún fichero menciona AWS, ECS, ECR, ElastiCache ni DynamoDB. Se comprueba tras F9, que borra
  este fichero — hoy es el único sitio donde siguen apareciendo esas palabras.
