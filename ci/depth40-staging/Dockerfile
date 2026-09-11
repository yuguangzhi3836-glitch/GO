FROM scratch
COPY rootfs/ /
COPY --chown=10001:10001 empty-state/ /state/
ENV PATH=/opt/go/python/bin LD_LIBRARY_PATH=/opt/go/python/lib PYTHONHOME=/opt/go/python PYTHONPATH=/opt/go/source/src:/opt/go/site PYTHONDONTWRITEBYTECODE=1 LANG=C.UTF-8 SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
USER 10001:10001
WORKDIR /opt/go/source
EXPOSE 8000
ENTRYPOINT ["/opt/go/python/bin/python3.13", "-B", "/opt/go/staging/launch.py"]
CMD ["preflight"]
