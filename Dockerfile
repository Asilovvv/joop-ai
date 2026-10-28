FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY joop ./joop
# business.yaml and data/ are mounted at run time (see docker-compose.yml)
CMD ["python", "-m", "joop"]
