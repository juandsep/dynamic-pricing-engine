PROMPT PARA EL SIGUIENTE AGENTE — Motor de Precios Dinámicos (dp) → Azure

CONTEXTO
- Repo: juandsep/dynamic-pricing-engine (trabaja SOLO dentro de esa carpeta).
- Proyecto Python gestionado con `uv` (pyproject.toml + uv.lock). Entry: `uv run dp`.
- Estado actual: scaffolding funcional.
  src/dp/{__init__,api,thompson,store}.py · tests/test_dp.py (1 passed) ·
  scripts/retrain.py · Dockerfile · README.md · PLAN.md · infra/README.md ·
  monitoring/README.md · .github/workflows/ci.yml · pyproject.toml.
- HOY la documentación e infra apuntan a AWS (ECS/ECR/ElastiCache/DynamoDB). Hay que migrar TODO a Azure.
- No toques otros repos. Referencia de estructura/CI: the uplift-modeling-pipeline project.

OBJETIVO
Dejar el proyecto listo para desplegar y operar 100% en Azure (sin rastro de AWS).

STACK A USAR
- Cómputo: Azure Container Apps (preferido) o AKS.
- Imágenes: Azure Container Registry (ACR).
- Feature store online: Azure Cache for Redis. Persistencia/eventos: Azure Cosmos DB (NoSQL, serverless) o Azure Table Storage.
- Secretos: Azure Key Vault. Observabilidad: Application Insights + Log Analytics.
- Tracking ML: MLflow propio en Container Apps (o Azure ML), expuesto vía MLFLOW_TRACKING_URI.
- CI/CD: GitHub Actions con OIDC federado (azure/login@v2), sin secretos estáticos.

TAREAS (en orden)
1. Crea la rama `chore/azure-migration` a partir de `dev`.
2. Reescribe README.md: arquitectura, variables de entorno (AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, ACR_NAME, CONTAINERAPP_NAME, REDIS_URL, COSMOS_ENDPOINT, COSMOS_DATABASE, MLFLOW_TRACKING_URI), sección de despliegue Azure y quickstart con uv.
3. Reescribe PLAN.md: fases F5/F6/F7 apuntando a Azure.
4. Reescribe infra/README.md y añade Terraform `azurerm`:
   infra/{main.tf,variables.tf,outputs.tf,terraform.tfvars.example} con ACR, Container Apps Environment + App, Azure Cache for Redis, Cosmos DB, Key Vault y Log Analytics.
5. Actualiza src/dp/store.py: sustituye boto3/redis-AWS por SDK Azure (azure-identity, azure-cosmos, redis-py contra Azure Cache). Mantén la interfaz pública `get_features(user_id)` / `set_features(user_id, features)`.
6. Añade dependencias con `uv add azure-identity azure-cosmos azure-keyvault-secrets` y actualiza uv.lock.
7. Actualiza .github/workflows/ci.yml: job `build` (uv sync + pytest + docker build) y job `deploy` (push a ACR + `az containerapp update`), deploy solo en push a `dev`.
8. Añade .github/workflows/retrain.yml: cron semanal que ejecuta `uv run python scripts/retrain.py` y registra la política en MLflow.
9. Verifica en local: `uv sync && uv run pytest -q` (verde) y `docker build -t dp .` (OK). Ejecuta `terraform validate` dentro de infra/ si aplica.

REGLAS
- Git flow: ramas topic desde `dev`, PR hacia `dev`; solo `dev` → `main`.
- Cero secretos en el repo: Key Vault + OIDC federado.
- Documentación en español; código/comentarios en inglés.
- Entrega final: lista de archivos cambiados + comandos ejecutados y su salida real (sin inventar resultados).

CRITERIO DE ACEPTACIÓN
- Ningún archivo del repo menciona AWS/ECS/ECR/ElastiCache/DynamoDB.
- Terraform de Azure pasa `terraform validate`.
- `uv run pytest -q` en verde y `docker build` OK.
- Workflows de GitHub Actions referencian Azure (ACR + Container Apps) con autenticación OIDC.
