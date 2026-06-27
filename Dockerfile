FROM python:3.12-slim

WORKDIR /app

# System deps for Pillow are already in the slim wheels; no apt needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY artframe ./artframe
COPY backend ./backend
COPY static ./static

ENV DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
