# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8501
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
RUN useradd -m appuser
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY streamlit_twitterapi_io_app.py ./streamlit_twitterapi_io_app.py
EXPOSE 8501
USER appuser
CMD streamlit run streamlit_twitterapi_io_app.py --server.port=$PORT --server.address=0.0.0.0
