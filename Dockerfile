FROM python:3.10-slim

WORKDIR /app

# Установка системных зависимостей (если понадобятся)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY bot.py .

# Создаём директории для данных
RUN mkdir -p temp_storage memes

# Тома для сохранения данных
VOLUME ["/app/temp_storage", "/app/memes", "/app"]

# Запуск
CMD ["python", "bot.py"]