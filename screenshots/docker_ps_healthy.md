Generated at: 2026-05-31 23:38:32 MSK

# docker ps healthy evidence

Command:

```bash
MLFLOW_PORT=15000 docker compose ps mlflow
```

Output:

```text
NAME           IMAGE              COMMAND                  SERVICE   CREATED          STATUS                    PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    58 seconds ago   Up 46 seconds (healthy)   0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
```
