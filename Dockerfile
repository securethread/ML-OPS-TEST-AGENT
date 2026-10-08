FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seed synthetic data at build time; re-seeded on container start too.
RUN python seed_data.py

EXPOSE 8000
ENV HOST=0.0.0.0 PORT=8000

# Re-seed (idempotent) then launch.
CMD ["sh", "-c", "python seed_data.py && python run.py"]
