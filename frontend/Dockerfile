FROM node:20-alpine
WORKDIR /app
COPY package.json tsconfig.json next-env.d.ts next.config.ts ./
RUN npm install
COPY app ./app
RUN npm run build
EXPOSE 3000
CMD ["npm","start"]
