FROM python:3.11-slim

# Don't write .pyc files, and send logs straight to the terminal instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Requirements are copied and installed before the code, so Docker reuses this layer
# (and skips reinstalling) until requirements.txt itself changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Django's development server: fine for a local demo, not for production (see the README).
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
