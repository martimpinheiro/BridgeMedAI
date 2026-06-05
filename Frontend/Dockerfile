FROM node:20-alpine

WORKDIR /app

# Copiar ficheiros de dependências primeiro
COPY package*.json ./

# Instalar dependências
RUN npm install

# Copiar o resto do código
COPY . .

EXPOSE 5173

# Arrancar o servidor de desenvolvimento do Vite expondo para a rede do contentor
CMD ["npm", "run", "dev", "--", "--host"]