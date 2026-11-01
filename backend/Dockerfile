FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
ENV PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_PROGRESS_BARS=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
WORKDIR /app
COPY pyproject.toml .
COPY gallery ./gallery
RUN pip install --no-cache-dir '.[model]'
RUN useradd --create-home --uid 10001 gallery
USER gallery
ENTRYPOINT ["fieldnotes"]
CMD ["serve", "--data", "/data", "--seed", "/seed.zip", "--model", "/models/giant", "--mode", "live", "--adapter", "/models/adapters/campus-run2"]
