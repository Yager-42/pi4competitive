# pi4competitive-tool-worker — pinned AIO-derived AgentTool worker image.
#
# P3.3 / agent-tool-sandbox-v1 (G17/G18/G22):
#   - FROM the exact AIO 1.11.0 manifest digest; no floating tags.
#   - The AIO base expects a root bootstrap (creates the `gem` user, chowns
#     writable paths, runs supervisord as root).  The locked production
#     baseline runs the container as a numeric non-root user with cap-drop=ALL
#     and a read-only rootfs, so this derived image pre-creates the user and
#     every writable path at build time and neutralizes the privileged init
#     steps that become redundant no-ops.
#   - The image adds only the fixed JSONL worker, the approved capability
#     code and its exact dependencies; no FastAPI, LLM provider, Agent loop,
#     session or workflow control-plane code is copied in.
#
# Build:  docker build -f deploy/tool-sandbox/Dockerfile \
#           --build-arg TOOL_WORKER_BUILD_IDENTITY=<derived-digest> .
# The derived image digest recorded in production config is the
# TOOL_WORKER_BUILD_IDENTITY value baked into the approved manifest.

FROM ghcr.io/agent-infra/sandbox@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7

# --- G18 hardening patch layer ------------------------------------------------
#
# The AIO base expects a root bootstrap (it creates the `gem` user, chowns
# writable paths, runs supervisord as root and rewrites its own nginx configs
# on the image filesystem).  The locked production baseline runs the container
# as a numeric non-root user with cap-drop=ALL and a read-only rootfs, so this
# derived image pre-creates the user, neutralizes the privileged init steps
# that become no-ops, and redirects every runtime config rewrite into a
# tmpfs-backed /run/gem tree that nginx and supervisord read from instead.
RUN set -eux; \
    groupadd -g 1000 gem \
    && useradd -u 1000 -g 1000 -d /home/gem -m -s /bin/bash gem \
    && sed -i 's/^user=root/user=gem/' /opt/gem/supervisord.conf \
    && sed -i 's|chown=root:%(ENV_USER)s|chown=gem:gem|' /opt/gem/supervisord.conf \
    && sed -i 's|files=/opt/gem/supervisord/\*\.conf|files=/run/gem/supervisord/*.conf|' /opt/gem/supervisord.conf \
    && sed -i 's/^user=root/user=%(ENV_USER)s/' /opt/gem/supervisord/nginx.conf \
    && sed -i 's|include /opt/gem/nginx-server-active.conf;|include /run/gem/nginx-server-active.conf;|' /opt/gem/nginx.conf \
    && sed -i 's|include /opt/gem/nginx-server-port-proxy.conf;|include /run/gem/nginx-server-port-proxy.conf;|' /opt/gem/nginx.conf \
    && sed -i 's|include /opt/gem/nginx-proxy-map.conf;|include /run/gem/nginx-proxy-map.conf;|' /opt/gem/nginx.conf \
    && sed -i 's|/opt/gem/nginx/\*\.conf|/run/gem/nginx/*.conf|' /opt/gem/nginx-server-without-auth.conf /opt/gem/nginx-server-with-auth.conf \
    && sed -i '1i error_log /dev/stderr;' /opt/gem/nginx.conf \
    && sed -i 's|ACTIVE_CONFIG="/opt/gem/nginx-server-active.conf"|ACTIVE_CONFIG="/run/gem/nginx-server-active.conf"|' /opt/gem/gem.sh \
    && sed -i 's|>"/opt/gem/nginx-server-port-proxy.conf"|>"/run/gem/nginx-server-port-proxy.conf"|' /opt/gem/gem.sh \
    && sed -i 's|rm -f /opt/gem/supervisord/supervisord.gost.conf|:|' /opt/gem/gem.sh \
    && sed -i 's|> /opt/gem/mcp-hub.json && rm -f /opt/gem/mcp-hub.json.template|> /run/gem/mcp-hub.json|' /opt/gem/gem.sh \
    && sed -i 's|touch /opt/gem/nginx-proxy-map.conf|touch /run/gem/nginx-proxy-map.conf|' /opt/gem/gem.sh \
    && sed -i 's|runtime_policy_path="/etc/browser/policies/managed/${runtime_policy_file}"|runtime_policy_path="/run/gem/policies/${runtime_policy_file}"|' /opt/gem/gem.sh \
    && sed -i 's|--mcp-config /opt/gem/mcp-hub.json|--mcp-config /run/gem/mcp-hub.json|' /opt/gem/supervisord/supervisord.python_srv.conf \
    && sed -i 's|/opt/gem/nginx/|/run/gem/nginx/|g' /opt/gem/gem.sh \
    && sed -i '/^set -e$/a chown() { :; }\ngroupadd() { :; }\nuseradd() { :; }\nsu() { :; }\nmkdir -p /run/gem/nginx /run/gem/supervisord /run/gem/policies\ncp -a /opt/gem/nginx/. /run/gem/nginx/\ncp -a /opt/gem/supervisord/. /run/gem/supervisord/\nrm -f /run/gem/supervisord/supervisord.gost.conf' /opt/gem/gem.sh
# --- Worker layer --------------------------------------------------------------
# Disable the unused AIO services (G17/G18): only nginx + python-server run.
ENV PYTHONPATH=/opt/pi4competitive \
    DISABLE_BROWSER=true \
    DISABLE_JUPYTER=true \
    DISABLE_CODE_SERVER=true \
    DISABLE_VNC=true \
    DISABLE_NODEJS_REPL=true \
    DISABLE_MCP_BROWSER=true

# Worker package: the image replaces sandbox/__init__.py with a minimal marker
# (worker_pkg/sandbox_init.py) so importing the worker never touches the host
# Pi control plane.  The approved tool manifest is baked below and read from
# the fixed worker path.
COPY competitive_app/src/competitive_app/__init__.py /opt/pi4competitive/competitive_app/__init__.py
COPY competitive_app/src/competitive_app/adapter/__init__.py /opt/pi4competitive/competitive_app/adapter/__init__.py
COPY competitive_app/src/competitive_app/adapter/out/__init__.py /opt/pi4competitive/competitive_app/adapter/out/__init__.py
COPY competitive_app/src/competitive_app/adapter/out/sandbox /opt/pi4competitive/competitive_app/adapter/out/sandbox
COPY deploy/tool-sandbox/worker_pkg/sandbox_init.py /opt/pi4competitive/competitive_app/adapter/out/sandbox/__init__.py

# Approved capability code only (echo + the three search providers); the
# worker imports their module-level four-argument execute functions directly.
COPY capability_packages/echo_example/extensions /opt/pi4competitive/capability_packages/echo_example/extensions
COPY capability_packages/search_tavily/extensions /opt/pi4competitive/capability_packages/search_tavily/extensions
COPY capability_packages/search_anysearch/extensions /opt/pi4competitive/capability_packages/search_anysearch/extensions
COPY capability_packages/search_grok/extensions /opt/pi4competitive/capability_packages/search_grok/extensions

COPY deploy/tool-sandbox/approved_tools.json /opt/pi4competitive/approved_tools.json
COPY deploy/tool-sandbox/licenses /opt/pi4competitive/licenses

ARG TOOL_WORKER_BUILD_IDENTITY=dev-unbuilt
RUN sed -i "s|dev-unbuilt|${TOOL_WORKER_BUILD_IDENTITY}|g" /opt/pi4competitive/approved_tools.json
