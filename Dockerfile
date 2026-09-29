# Use official Python slim image
FROM python:3.11-slim

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Set workdir
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies using uv
RUN uv sync --frozen

# Expose port for FastAPI
EXPOSE 8000

# Command to run the service
CMD ["uv", "run", "python", "-m", "dp"]
