# No-network sandbox for the model/pickle work (design §6.3): scan artifacts, never execute them.
# Build:  docker build -t assetscan-sandbox skills/tool-assetscan
# Run:    docker run --rm --network none -v "$PWD/sets:/sets:ro" -v "$PWD/out:/out" assetscan-sandbox <cmd>
FROM python:3.11-slim
RUN pip install --no-cache-dir modelaudit fickling 2>/dev/null || pip install --no-cache-dir fickling
WORKDIR /work
# The container is run with --network none; nothing here reaches the internet or unpickles input.
ENTRYPOINT ["bash", "-lc"]
