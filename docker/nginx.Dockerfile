# syntax=docker/dockerfile:1.10

ARG NGINX_IMAGE=nginx:1.30.4-alpine3.24
FROM ${NGINX_IMAGE}
RUN apk add --no-cache gettext \
    && install -d -o nginx -g nginx -m 0750 /run/nginx /var/cache/nginx /var/log/mdlbot \
    && rm -f /etc/nginx/conf.d/default.conf
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker/nginx/site.conf.template /etc/nginx/templates/site.conf.template
COPY docker/nginx/trusted-proxies.conf /etc/nginx/trusted-proxies.conf
COPY --chmod=0555 --chown=nginx:nginx docker/nginx/entrypoint.sh /usr/local/bin/mdlbot-nginx-entrypoint
USER nginx
EXPOSE 8080 8443
ENTRYPOINT ["/usr/local/bin/mdlbot-nginx-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
