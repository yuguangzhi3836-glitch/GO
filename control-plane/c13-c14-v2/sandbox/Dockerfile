# Build-time network only. Runtime accepts the resulting immutable image ID.
FROM postgres:18.4-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
COPY pyproject.toml /opt/dependencies/pyproject.toml
RUN /opt/venv/bin/python -c 'import tomllib,subprocess; p=tomllib.load(open("/opt/dependencies/pyproject.toml","rb"))["project"]; subprocess.check_call(["/opt/venv/bin/pip","install",*p["dependencies"],*p["optional-dependencies"]["dev"]])' \
    && /opt/venv/bin/pip freeze > /opt/dependencies/installed.txt \
    && useradd --uid 65532 --no-create-home --home-dir /work c14
COPY sandbox_payload.py /opt/c14/sandbox_payload.py
ENV PATH=/opt/venv/bin:/usr/lib/postgresql/18/bin:/usr/bin:/bin
USER 65532:65532
ENTRYPOINT ["/opt/venv/bin/python", "-I", "/opt/c14/sandbox_payload.py"]
