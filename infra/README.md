# Infra — DP (Terraform)

Provisiona los recursos de AWS para el motor de precios:

- **ECS Fargate**: servicio `dp-api` (imagen desde ECR).
- **ECR**: repositorio de imágenes.
- **ElastiCache (Redis)**: feature store online.
- **DynamoDB**: tabla de eventos/atributos (`pk=user_id`, `sk=ts`).
- **IAM / Secrets Manager**: credenciales de MLflow y accesos.

Notas: mantener un módulo por recurso y un `terraform.tfvars.example` por entorno.
Referencia de estructura: `../../portfolio/portfolio-infra`.
