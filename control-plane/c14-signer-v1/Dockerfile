FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY c14_signer.py app.py ./
USER 65532
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=1", "--threads=4", "app:application"]
