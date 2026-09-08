FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY app /app/app
RUN useradd -m -u 10001 radar && mkdir -p /data && chown radar:radar /data
USER radar
EXPOSE 8080
CMD ["python", "-m", "app.main"]
