#!/bin/sh
#
# Install Thorsten Otto's prebuilt m68k-atari-mintelf GCC cross toolchain
# (GCC + binutils + mintbin + mintlib + fdlibm + gemlib) into a user
# directory, no root needed.  https://tho-otto.de/crossmint.php
#
# Usage: fetch-cross-mint.sh [install-dir]   (default ~/computers/atari-cc)
# Then:  export PATH=<install-dir>/opt/cross-mint/bin:$PATH
#
# The prebuilt tools are x86-64 only:
#  - macOS on Apple Silicon runs them through Rosetta
#    (softwareupdate --install-rosetta).
#  - Linux on arm64 runs them through binfmt qemu-x86_64.  If it isn't
#    registered yet, Docker can do it:
#      docker run --privileged --rm tonistiigi/binfmt --install amd64
#    The x86-64 libraries they need are copied out of an amd64 ubuntu image
#    into <install-dir>/x86-root (needs Docker), and opt/cross-mint/bin
#    holds small wrappers that point qemu at them.
#    That works but compiles several times slower than native; for a native
#    toolchain (same versions, built from source in Docker in 15-30 minutes)
#    use build-cross-mint.sh instead.

set -e

DEST=${1:-$HOME/computers/atari-cc}
URL=https://tho-otto.de/download/mint
case "$(uname -s)" in
	Darwin) HOST=macos ;;
	Linux)  HOST=linux64 ;;
	*) echo "unsupported host $(uname -s)" >&2; exit 1 ;;
esac

TOOLS="binutils-2.45-mintelf-20250812-bin-$HOST.tar.xz
gcc-14.3.0-mintelf-20250702-bin-$HOST.tar.xz
mintbin-0.4-mintelf-20230911-bin-$HOST.tar.xz"
LIBS="mintlib-0.60.1-mintelf-20240718-dev.tar.xz
fdlibm-20240425-mintelf-dev.tar.xz
gemlib-0.44.0-mintelf-20240425-dev.tar.xz"

mkdir -p "$DEST/dl" "$DEST/libtmp"
cd "$DEST"
for f in $TOOLS $LIBS; do
	[ -f "dl/$f" ] || { echo "Fetching $f"; curl -fsSL -o "dl/$f" "$URL/$f"; }
done
if [ "$HOST" = linux64 ]; then
	# the Linux tarballs are laid out for /usr; install them where the macOS
	# ones go (the toolchain is relocatable)
	rm -rf usrtmp opt/cross-mint && mkdir -p usrtmp opt
	for f in $TOOLS; do
		tar xJf "dl/$f" -C usrtmp
	done
	mv usrtmp/usr opt/cross-mint && rm -rf usrtmp
else
	for f in $TOOLS; do
		tar xJf "dl/$f"
	done
fi
# libraries are packaged for /usr/m68k-atari-mintelf/sys-root, while
# the (relocatable) GCC looks for its sysroot next to its own install
for f in $LIBS; do
	tar xJf "dl/$f" -C libtmp
done
mkdir -p opt/cross-mint/m68k-atari-mintelf/sys-root
cp -R libtmp/usr/m68k-atari-mintelf/sys-root/. opt/cross-mint/m68k-atari-mintelf/sys-root/
rm -rf libtmp

if [ "$HOST" = linux64 ] && [ "$(uname -m)" != x86_64 ]; then
	[ -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ] || {
		echo "x86-64 programs can't run here yet; register qemu-x86_64 with:" >&2
		echo "  docker run --privileged --rm tonistiigi/binfmt --install amd64" >&2
		exit 1; }
	command -v docker >/dev/null || { echo "Docker is needed to fetch the x86-64 libraries" >&2; exit 1; }
	echo "Copying x86-64 libraries from ubuntu:24.04 (amd64) into $DEST/x86-root"
	docker pull -q --platform linux/amd64 ubuntu:24.04 >/dev/null
	c=$(docker create --platform linux/amd64 ubuntu:24.04 true)
	rm -rf x86-root && mkdir x86-root
	docker export "$c" | tar -x -C x86-root lib lib64 usr/lib/x86_64-linux-gnu usr/lib64
	docker rm "$c" >/dev/null
	# bin.x86 holds the real tools; each bin/ entry runs its namesake with the
	# x86-64 libraries (other tools reach them through symlinks into bin/)
	B=opt/cross-mint
	mv "$B/bin" "$B/bin.x86" && mkdir "$B/bin"
	for f in "$B"/bin.x86/*; do
		n=$(basename "$f")
		cat > "$B/bin/$n" <<-EOF
		#!/bin/sh
		# x86-64 tool run through binfmt qemu-x86_64, with the libraries in atari-cc/x86-root
		D=\$(dirname "\$(readlink -f "\$0")")
		QEMU_LD_PREFIX="\${QEMU_LD_PREFIX:-\$D/../../../x86-root}" exec "\$D/../bin.x86/$n" "\$@"
		EOF
		chmod +x "$B/bin/$n"
	done
fi

GCC=$DEST/opt/cross-mint/bin/m68k-atari-mintelf-gcc
"$GCC" --version | head -1
echo "sysroot: $("$GCC" -print-sysroot)"
echo "Add to PATH: export PATH=$DEST/opt/cross-mint/bin:\$PATH"
