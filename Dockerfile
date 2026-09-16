FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# deps first for layer caching
COPY tars/requirements.txt /app/tars/requirements.txt
RUN pip install -r /app/tars/requirements.txt

# app
COPY . /app

# build the universe cache at image build (best-effort; app also builds lazily)
RUN python -m tars.universe_builder || true

EXPOSE 8000
CMD ["sh", "-c", "uvicorn tars.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
