web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
web-mtls: gunicorn config.wsgi:application --bind 0.0.0.0:8443 --workers 2 --certfile=certs/server.crt --keyfile=certs/server.key --ca-certs=certs/ca.crt --cert-reqs=2
# Windows: gunicorn doesn't work on Windows. Use instead:
#   python scripts/run_mtls_server.py
