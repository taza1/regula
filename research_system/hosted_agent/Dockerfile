FROM python:3.13-slim
WORKDIR /app
COPY hosted_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home agent
COPY src/config.py src/model_client.py /app/src/
RUN touch /app/src/__init__.py
COPY hosted_agent/main.py /app/main.py
USER agent
EXPOSE 8088
CMD ["python", "main.py"]
