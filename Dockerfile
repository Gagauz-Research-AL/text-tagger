FROM python:3.12-slim

WORKDIR /app
COPY tagger.py mock_data.py server.py ./
COPY static/ static/

EXPOSE 8000
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8000"]
