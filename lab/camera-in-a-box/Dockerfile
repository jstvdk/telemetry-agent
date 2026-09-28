# syntax=docker/dockerfile:1.7
#
# camera-in-a-box: one camera server on AlmaLinux 9 (the production OS), with systemd as
# PID 1 running the orchestrator's own user units unchanged. Hardware is replaced by the
# software mocks via systemd drop-ins (systemd/user/*.d/mock.conf).
#
# Build contexts (see Makefile):  default = this directory
#                                 sstcam  = .build/sstcam-server   (staged by stage.sh)
#                                 cambridge = .build/cambridge

FROM almalinux:9 AS os
ENV container=docker LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN dnf -y install epel-release \
 && dnf -y install --allowerasing \
      systemd systemd-container dbus-daemon procps-ng util-linux iproute iproute-tc iputils \
      python3.12 python3.12-devel gcc gcc-c++ make git git-lfs wget tar gzip bzip2 which \
      sudo less jq rsync stress-ng \
 && dnf clean all \
 && rm -rf /var/cache/dnf
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/

# cfitsio, built exactly as the project's CI image does
COPY --from=sstcam env/install-cfitsio.sh /tmp/install-cfitsio.sh
RUN cd /tmp && bash install-cfitsio.sh >/dev/null && rm -rf /tmp/FitsIO /tmp/install-cfitsio.sh \
 && echo /usr/local/lib > /etc/ld.so.conf.d/local.conf && ldconfig

RUN useradd -m -u 1000 -G wheel sstcam \
 && echo 'sstcam ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/sstcam \
 && mkdir -p /opt/sstcam /data/SSTCAM && chown -R sstcam:sstcam /opt/sstcam /data

# ---------------------------------------------------------------------------------------
FROM os AS build
USER sstcam
WORKDIR /opt/sstcam/src
COPY --from=sstcam --chown=sstcam:sstcam . sstcam-server
COPY --from=cambridge --chown=sstcam:sstcam . cambridge
# GIT_LFS_SKIP_SMUDGE: corel-mmio's remote is missing an LFS object (a logo); nothing
# installed needs LFS content, so dependency checkouts keep pointer files.
ENV VIRTUAL_ENV=/opt/sstcam/venv PATH=/opt/sstcam/venv/bin:$PATH UV_LINK_MODE=copy \
    UV_CACHE_DIR=/home/sstcam/.cache/uv GIT_LFS_SKIP_SMUDGE=1 \
    CFLAGS=-fsigned-char CXXFLAGS=-fsigned-char
# -fsigned-char: the camera servers are x86 (char is signed). On arm64 char is unsigned and
# eventbuilder's run_udp_stress_test.cc (`char arg = getopt(...); arg != -1`) fails -Werror.
# Upstream bug, reported in docs/PROVENANCE.md; x86 semantics here instead of patching source.

RUN uv venv -p /usr/bin/python3.12 $VIRTUAL_ENV

# 1. pinned third-party requirements; the only SSH-hosted dependency (cambridge) is
#    installed from the local copy instead. corel-* come from public DESY GitLab (https).
RUN --mount=type=cache,target=/home/sstcam/.cache/uv,uid=1000,gid=1000 \
    cd sstcam-server \
 && grep -v '^cambridge @' requirements.txt > /tmp/requirements.txt \
 && uv pip install -r /tmp/requirements.txt \
 && uv pip install ../cambridge

# 2. sstcam packages, in the order of the project's justfile (`install-all`)
RUN --mount=type=cache,target=/home/sstcam/.cache/uv,uid=1000,gid=1000 \
    cd sstcam-server \
 && uv pip install 'scikit-build-core[pyproject]==0.11.5' 'cmake==3.31.6' \
 && uv pip install './sstcam-waveform' --no-build-isolation-package=sstcam-waveform
RUN --mount=type=cache,target=/home/sstcam/.cache/uv,uid=1000,gid=1000 \
    cd sstcam-server \
 && uv pip install \
      ./sstcam-telecom ./sstcam-configuration ./sstcam-cli ./sstcam-tui \
      ./sstcam-eventbuilder --no-build-isolation-package=sstcam-eventbuilder \
      ./sstcam-slowsignal ./sstcam-target ./sstcam-backplane ./sstcam-chiller \
      ./sstcam-flasher ./sstcam-slowboard ./sstcam-pointing ./sstcam-gatherer \
      './sstcam-controller[hardware]' ./sstcam-aiv ./sstcam-orchestrator \
 && sstcam --help >/dev/null

# ---------------------------------------------------------------------------------------
FROM os AS runtime
ARG SSTCAM_SERVER_REV=unknown SSTCAM_SERVER_BRANCH=unknown CAMBRIDGE_REV=unknown
LABEL org.opencontainers.image.title="camera-in-a-box" \
      sstcam.server.rev=$SSTCAM_SERVER_REV sstcam.server.branch=$SSTCAM_SERVER_BRANCH \
      cambridge.rev=$CAMBRIDGE_REV

COPY --from=build --chown=sstcam:sstcam /opt/sstcam/venv /opt/sstcam/venv
COPY --from=sstcam --chown=sstcam:sstcam sstcam-orchestrator/units /opt/sstcam/units

# The upstream unit files hard-code %h/miniforge3/envs/sstcam; point that path at the venv
# so the units run unchanged.
RUN mkdir -p /home/sstcam/miniforge3/envs /home/sstcam/miniconda3/envs \
 && ln -s /opt/sstcam/venv /home/sstcam/miniforge3/envs/sstcam \
 && ln -s /opt/sstcam/venv /home/sstcam/miniconda3/envs/sstcam

# Configuration: the LOCAL_DB config directory from the source tree, patched for mocks
# (see config/patch_config.py); the rest of data/ (mapping, catalog, calibration tables) as is.
COPY --from=sstcam --chown=sstcam:sstcam sstcam-configuration/sstcam_configuration/data /opt/sstcam/data
COPY config/patch_config.py config/merge_slowsignal_calib.py /opt/sstcam/
RUN cp -r /opt/sstcam/data/config /etc/sstcam \
 && /opt/sstcam/venv/bin/python /opt/sstcam/patch_config.py /etc/sstcam \
 && /opt/sstcam/venv/bin/python /opt/sstcam/merge_slowsignal_calib.py /opt/sstcam/data/slowsignal \
 && chown -R sstcam:sstcam /etc/sstcam /opt/sstcam/data

# systemd: user units (upstream, unchanged) + our drop-ins/extra units; lingering user
# manager starts sstcam.target at boot; persistent journal.
COPY --chown=sstcam:sstcam systemd/user/ /home/sstcam/.config/systemd/user/
COPY --chown=sstcam:sstcam systemd/environment.d/ /home/sstcam/.config/environment.d/
# Backplane: masked. The first camera version runs without a backplane and its server
# crash-loops when backplane_connection=DISCONNECTED (known upstream issue).
RUN cp -n /opt/sstcam/units/* /home/sstcam/.config/systemd/user/ \
 && ln -sf /dev/null /home/sstcam/.config/systemd/user/sstcam-backplane.service \
 && mkdir -p /home/sstcam/.config/systemd/user/default.target.wants \
 && ln -sf ../sstcam.target /home/sstcam/.config/systemd/user/default.target.wants/sstcam.target \
 && chown -R sstcam:sstcam /home/sstcam \
 && mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/sstcam \
 && mkdir -p /var/log/journal /etc/systemd/journald.conf.d \
 && printf '[Journal]\nStorage=persistent\nRateLimitBurst=0\nRateLimitIntervalSec=0\n' \
      > /etc/systemd/journald.conf.d/lab.conf \
 && systemctl unmask systemd-logind.service \
 && systemctl mask systemd-firstboot.service systemd-udevd.service systemd-udev-trigger.service \
      dnf-makecache.timer getty@tty1.service console-getty.service

COPY bin/ /usr/local/bin/
COPY --chown=sstcam:sstcam lab/ /opt/sstcam/lab/
ENV PATH=/opt/sstcam/venv/bin:$PATH
STOPSIGNAL SIGRTMIN+3
VOLUME ["/data", "/var/log/journal"]
CMD ["/usr/sbin/init"]
