FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY joop ./joop
COPY business.yaml ./business.yaml
CMD ["python", "-m", "joop"]
