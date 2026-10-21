ARG BASE_IMAGE=nginxinc/nginx-unprivileged@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
FROM ${BASE_IMAGE}
ARG RUNTIME_CONTEXT_ID
LABEL isometric.tokyo/runtime-context=${RUNTIME_CONTEXT_ID}
COPY nginx.conf /etc/nginx/nginx.conf
COPY site/ /srv/site/
COPY retained/ /srv/retained/
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
CMD []
