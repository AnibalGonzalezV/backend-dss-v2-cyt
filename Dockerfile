# Usar imagen de Python ligera y estable
FROM python:3.12-slim

# Evita que Python escriba archivos .pyc en el disco
ENV PYTHONDONTWRITEBYTECODE 1
# Fuerza a que stdout y stderr se envíen directamente a la terminal
ENV PYTHONUNBUFFERED 1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para PostgreSQL y librerías C
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instalar librerías de Python
COPY requirements.txt /app/
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copiar el código del proyecto
COPY . /app/

# Exponer el puerto interno de Django
EXPOSE 8000

# El comando por defecto será arrancar el servidor web
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
