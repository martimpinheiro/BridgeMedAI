FROM python:3.11-slim

WORKDIR /app

# Instalar dependências de sistema (incluindo drivers ODBC para o SQL Server)
RUN apt-get update && apt-get install -y \
    curl apt-transport-https gnupg2 \
    unixodbc-dev g++ \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código do Backend
COPY . .

# O entrypoint da aplicação está na pasta Python
WORKDIR /app/Python

EXPOSE 8000

# Arrancar o servidor
CMD ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]