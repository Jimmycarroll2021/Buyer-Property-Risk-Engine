FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock /app/
COPY src /app/src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps -e .
COPY config /app/config
COPY examples /app/examples
COPY web /app/web
COPY docs /app/docs
RUN useradd --create-home --uid 10001 risk && mkdir /app/runtime && chown -R risk:risk /app/runtime
USER risk
ENV RISK_DATA_DIR=/app/runtime RISK_PROJECT_ROOT=/app
EXPOSE 8000
CMD ["python", "-m", "riskengine", "serve", "--host", "0.0.0.0", "--port", "8000"]

