FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked into the client bundle at build time; point it at the deployed backend.
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:22-alpine

WORKDIR /app
COPY --from=build /app /app

ENV PORT=5173
EXPOSE 5173

CMD ["sh", "-c", "npx vinext start -p ${PORT}"]
