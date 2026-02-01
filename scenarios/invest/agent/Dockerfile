FROM python:3.11-slim

# Keep Python output unbuffered and avoid .pyc files
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage layer caching
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scenarios ./scenarios

RUN pip install --no-cache-dir .

EXPOSE 9119

# ENTRYPOINT must accept --host/--port/--card-url as per AgentBeats runner contract
ENTRYPOINT ["python", "scenarios/invest/agent/src/server.py"]
CMD ["--host", "0.0.0.0", "--port", "9119"]
