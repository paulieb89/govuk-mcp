FROM python:3.12-slim

WORKDIR /app

# Install build tools
RUN pip install --no-cache-dir hatchling

# Copy and install package
COPY pyproject.toml README.md ./
COPY govuk_mcp/ ./govuk_mcp/
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["govuk-mcp"]
