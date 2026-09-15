FROM node:24-alpine@sha256:50c8e8ca1d27439048670df5883f32d57cf81cff6233222c893fd0d9884cbd81
WORKDIR /app
COPY server.mjs /app/server.mjs
USER 1000:1000
EXPOSE 8080
CMD ["node", "/app/server.mjs"]
