FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

RUN useradd -r -u 1000 -g root mcp
USER mcp

EXPOSE 8000

CMD ["python", "server.py"]
