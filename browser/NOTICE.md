The seccomp_profile.json file is from Microsoft Playwright v1.63.0, utils/docker/seccomp_profile.json, licensed under Apache-2.0.
Source: https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json
The profile permits user-namespace sandbox operations in addition to the upstream Docker syscall policy.

PriSMA 0.8.1 adds a clone3 ENOSYS response (errno 38), matching the documented Docker glibc fallback policy, while retaining user-namespace sandbox calls. Source: https://docs.docker.com/engine/release-notes/23.0/

PriSMA 0.8.2 makes the chroot syscall allow-rule independent of the container's initial capability set. Chromium gains CAP_SYS_CHROOT inside a nested user namespace to drop filesystem access; Docker's initial CAP_SYS_CHROOT filter condition prevented that syscall when cap_drop is ALL. Container capability drops and Chromium sandboxing remain enabled. Primary source: https://chromium.googlesource.com/chromium/src/+/lkgr/sandbox/linux/services/credentials.cc
