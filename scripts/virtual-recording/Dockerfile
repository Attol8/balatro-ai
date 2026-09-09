FROM rust:1.90-bookworm AS lovely-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git cmake build-essential clang \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build/lovely
ENV CC=clang CXX=clang++ CARGO_BUILD_JOBS=2
RUN git init . \
    && git remote add origin https://github.com/ethangreen-dev/lovely-injector.git \
    && git fetch --depth 1 origin 91759da5702618c3b940fbbe8135954414c0ef34 \
    && git checkout --detach FETCH_HEAD \
    && git submodule update --init --recursive --depth 1 \
    && cargo +stable build --locked --release --package lovely-unix

FROM debian:bookworm-slim AS love-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential cmake pkg-config \
      libsdl2-dev libfreetype-dev libopenal-dev libmodplug-dev \
      libvorbis-dev libtheora-dev libogg-dev libmpg123-dev \
      libluajit-5.1-dev libgl1-mesa-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build/love
RUN git init . \
    && git remote add origin https://github.com/love2d/love.git \
    && git fetch --depth 1 origin f834ab72481e95fa90abf573643c8dd168ae0660 \
    && git checkout --detach FETCH_HEAD \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/usr/local -DCMAKE_INSTALL_RPATH=/usr/local/lib \
    && cmake --build build --parallel 2 \
    && nm -D build/libliblove.so | grep ' T PHYSFS_getMountPoint$' \
    && nm -D build/libliblove.so | grep ' T PHYSFS_mount$' \
    && nm -D build/libliblove.so | grep ' T PHYSFS_unmount$'

FROM debian:bookworm-slim
# LOVE's Debian post-install script registers its man page as an alternative.
# Slim images exclude man pages by default, which makes that script fail.
RUN printf 'path-include=/usr/share/man/*\n' > /etc/dpkg/dpkg.cfg.d/zz-love-manpages \
    && apt-get update && apt-get install -y --no-install-recommends \
      love libluajit-5.1-2 lua-socket xvfb x11-utils ffmpeg \
      libgl1-mesa-dri libglx-mesa0 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /mods /game /recording /runtime/home

COPY --from=lovely-builder /build/lovely/target/release/liblovely.so /usr/local/lib/liblovely.so
# Debian's monolithic LOVE 11.4 does not export embedded PhysFS for nativefs.
# Upstream's CMake build exposes the same filesystem state through liblove.so.
COPY --from=love-builder /build/love/build/love /usr/local/bin/love
COPY --from=love-builder /build/love/build/libliblove.so /usr/local/lib/libliblove.so
RUN ldconfig
COPY entrypoint.sh /usr/local/bin/virtual-recording
COPY bootstrap-settings.sh /usr/local/bin/bootstrap-recording-settings
RUN chmod 0755 /usr/local/bin/virtual-recording /usr/local/bin/bootstrap-recording-settings

ENV HOME=/runtime/home \
    XDG_DATA_HOME=/recording/saves \
    XDG_CONFIG_HOME=/runtime/home/.config \
    DISPLAY=:99 \
    LOVELY_MOD_DIR=/mods \
    LIBGL_ALWAYS_SOFTWARE=1 \
    SDL_AUDIODRIVER=dummy \
    ALSOFT_DRIVERS=null \
    BALATROBOT_HOST=0.0.0.0 \
    BALATROBOT_PORT=12346 \
    BALATROBOT_HEADLESS=0 \
    BALATROBOT_FAST=0 \
    BALATROBOT_RENDER_ON_API=0 \
    BALATROBOT_AUDIO=0 \
    BALATROBOT_ALL_UNLOCKED=1 \
    BALATROBOT_FPS_CAP=30 \
    RECORD_SECONDS=3600

EXPOSE 12346
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/virtual-recording"]
