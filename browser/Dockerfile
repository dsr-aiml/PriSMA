FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /observer
RUN pip install --no-cache-dir playwright==1.63.0 fastapi==0.143.0 uvicorn==0.54.0 httpx==0.28.1 graphql-core==3.3.0 && \
    mkdir -p /observer/app && touch /observer/app/__init__.py
COPY backend/app/public_files.py backend/app/web_observation.py backend/app/public_surface.py backend/app/page_access.py backend/app/resource_policy.py backend/app/read_operations.py /observer/app/
COPY browser/service.py browser/entrypoint.sh /observer/
USER pwuser
CMD ["sh", "/observer/entrypoint.sh"]
