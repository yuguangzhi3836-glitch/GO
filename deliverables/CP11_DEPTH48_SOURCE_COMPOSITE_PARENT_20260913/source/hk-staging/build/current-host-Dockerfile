FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY frontend ./frontend
COPY scripts/r82_rds_lineage_probe.py ./scripts/r82_rds_lineage_probe.py
COPY scripts/aoluguya_firecrawl_media_discovery.py scripts/aoluguya_real_media_harvest_gate.py scripts/aoluguya_hk_real_media_one_shot.sh ./scripts/
COPY tests/conftest.py tests/test_aoluguya_media_discovery_202.py tests/test_aoluguya_multi_source_media_rights.py tests/test_aoluguya_media_intelligence_v2.py tests/test_v61_media_harvester_rights_gate.py tests/test_aoluguya_live_media_discovery_manifest.py tests/test_aoluguya_firecrawl_provider.py ./tests/
COPY Dockerfile ./Dockerfile
COPY MEDIA_DISCOVERY_2_0_2_FINAL_CANDIDATE_MANIFEST.json ./
RUN pip install --no-cache-dir -e ".[dev]"
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "go_hotel.main:app", "--host", "0.0.0.0", "--port", "8000"]
