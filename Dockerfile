FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

COPY pyproject.toml setup.cfg README.md LICENSE ./
COPY src/ ./src/

RUN --mount=type=secret,id=pip_ca \
	if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
	python -m pip install --no-cache-dir .

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	XDG_DATA_HOME=/tmp/snow-mcp

EXPOSE 8080

ENTRYPOINT ["python", "-m", "servicenow_mcp_server"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
