#!/bin/sh
#
# Build the m68k-atari-mintelf cross toolchain from source for this machine's
# own CPU, in Docker (cross-mint-native/Dockerfile), and install it where
# fetch-cross-mint.sh puts the prebuilt one.  Same versions and MiNT patches
# as the prebuilt toolchain (binutils 2.45, GCC 14.3.0, mintbin 0.4), but no
# x86-64 emulation: use this on arm64 Linux, where the prebuilt tools only run
# through qemu-x86_64.  Takes about 15-30 minutes, once.
#
# Usage: build-cross-mint.sh [install-dir]   (default ~/computers/atari-cc)
# Then:  export PATH=<install-dir>/opt/cross-mint/bin:$PATH
#
# An existing opt/cross-mint (e.g. fetch-cross-mint.sh's) is kept as
# opt/cross-mint.prev.  The result runs on Linux hosts like the build one
# (glibc 2.39 or newer, zlib and zstd).

set -e

DEST=${1:-$HOME/computers/atari-cc}
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=cross-mint-native:gcc14.3.0
command -v docker >/dev/null || { echo "Docker is needed" >&2; exit 1; }

echo "Building $IMAGE (binutils, GCC, mintbin; logs: docker build output)"
docker build -t "$IMAGE" "$HERE/cross-mint-native"

mkdir -p "$DEST/opt"
c=$(docker create "$IMAGE" /none)
rm -rf "$DEST/opt/cross-mint.new"
docker cp "$c:/opt/cross-mint" "$DEST/opt/cross-mint.new"
docker rm "$c" >/dev/null
if [ -d "$DEST/opt/cross-mint" ]; then
	rm -rf "$DEST/opt/cross-mint.prev"
	mv "$DEST/opt/cross-mint" "$DEST/opt/cross-mint.prev"
fi
mv "$DEST/opt/cross-mint.new" "$DEST/opt/cross-mint"

GCC=$DEST/opt/cross-mint/bin/m68k-atari-mintelf-gcc
"$GCC" --version | head -1
echo "sysroot: $("$GCC" -print-sysroot)"
echo "Add to PATH: export PATH=$DEST/opt/cross-mint/bin:\$PATH"
