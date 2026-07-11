# Reproducible-results image for the Paritran prototype slice.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir networkx==3.4.2
COPY src/ ./src/
# Run the measured slice and print results.json to stdout.
CMD ["python", "src/paritran_prototype.py"]
