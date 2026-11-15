FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent_risque ./agent_risque
COPY alphaforge_starter ./alphaforge_starter
ENV PEACE_HOST=0.0.0.0 PEACE_ALLOWED_HOSTS=* PORT=8080 AWS_DEFAULT_REGION=us-east-1
EXPOSE 8080
CMD ["python", "-m", "agent_risque.app.server"]
