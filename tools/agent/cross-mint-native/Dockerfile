# Native build of the m68k-atari-mintelf cross toolchain: the same versions and
# MiNT patches as Thorsten Otto's prebuilt x86-64 one (binutils 2.45, GCC 14.3.0,
# mintbin 0.4), compiled for the build host's own CPU (arm64 Linux, or any other).
# Driven by ../build-cross-mint.sh, which copies /opt/cross-mint out of the image.
#
# Patches and configure options come from https://github.com/th-otto/crossmint
# (binutils-build.sh, gcc-14-build.sh, mintbin-build.sh), pinned below.

FROM ubuntu:24.04 AS build
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
        build-essential bison flex texinfo file curl ca-certificates xz-utils bzip2 patch \
        libzstd-dev zlib1g-dev m4 && rm -rf /var/lib/apt/lists/*

ARG CROSSMINT=53ff5e25af1cd679bb60d46ab4e808d559ae5af2
ARG GNU=https://ftp.gnu.org/gnu
ARG MINT=https://tho-otto.m68k.eu/download/mint
ARG TARGET=m68k-atari-mintelf
ARG PREFIX=/opt/cross-mint
ENV PATH=$PREFIX/bin:$PATH
WORKDIR /src
RUN P=https://raw.githubusercontent.com/th-otto/crossmint/$CROSSMINT/patches && \
    curl -fsSL $GNU/binutils/binutils-2.45.tar.xz | tar xJ && \
    curl -fsSL $GNU/gcc/gcc-14.3.0/gcc-14.3.0.tar.xz | tar xJ && \
    curl -fsSL $MINT/mintbin-0.4.tar.xz | tar xJ && \
    for l in mintlib-0.60.1-mintelf-20240718 fdlibm-20240425-mintelf gemlib-0.44.0-mintelf-20240425; do \
        curl -fsSL -o $l-dev.tar.xz $MINT/$l-dev.tar.xz; done && \
    curl -fsSL $P/binutils/binutils-2.45-mint-20250812.patch | patch -d binutils-2.45 -p1 -s && \
    curl -fsSL $P/binutils/binutils-m68k-segmentalign.patch | patch -d binutils-2.45 -p1 -s && \
    curl -fsSL $P/gcc/gcc-14.3.0-mint-20250702.patch | patch -d gcc-14.3.0 -p1 -s && \
    cd gcc-14.3.0 && ./contrib/download_prerequisites >/dev/null

# binutils (options from binutils-build.sh; the patched bfd needs the a.out
# m68k-atari-mint target too, which writes the .PRG files)
RUN mkdir b-binutils && cd b-binutils && ../binutils-2.45/configure \
        --target=$TARGET --prefix=$PREFIX --libexecdir='${libdir}' \
        --with-pkgversion="GNU Binutils for MiNT ELF 20250812" \
        --enable-targets="$(../binutils-2.45/config.guess),m68k-atari-mint" \
        --with-gcc --with-gnu-as --with-gnu-ld --disable-werror --disable-threads \
        --enable-lto --enable-plugins --disable-nls --with-system-zlib \
        --disable-gdb --disable-gdbserver --disable-sim --disable-readline --disable-gprofng \
        --with-sysroot=$PREFIX/$TARGET/sys-root >/dev/null && \
    make -j"$(nproc)" >/dev/null && make install >/dev/null

# the target libraries GCC builds against, in the sysroot next to it
RUN mkdir -p $PREFIX/$TARGET/sys-root && for f in *-dev.tar.xz; do tar xJf $f; done && \
    cp -R usr/$TARGET/sys-root/. $PREFIX/$TARGET/sys-root/ && rm -rf usr

# GCC, C and C++ (options and the target-library strip from gcc-14-build.sh; GMP/MPFR/MPC/ISL built in-tree,
# so the compiler needs nothing from the host but libc, zlib and zstd)
RUN mkdir b-gcc && cd b-gcc && ../gcc-14.3.0/configure \
        --target=$TARGET --prefix=$PREFIX --libexecdir='${libdir}' \
        --with-pkgversion="MiNT ELF 20250702" \
        CFLAGS_FOR_TARGET="-O2 -fomit-frame-pointer" CXXFLAGS_FOR_TARGET="-O2 -fomit-frame-pointer" \
        --disable-libcc1 --disable-werror \
        --with-gxx-include-dir=$PREFIX/$TARGET/sys-root/usr/include/c++/14 \
        --with-libstdcxx-zoneinfo=/usr/share/zoneinfo \
        --with-gcc-major-version-only --with-gcc --with-gnu-as --with-gnu-ld \
        --with-system-zlib --without-static-standard-libraries --without-stage1-ldflags \
        --disable-libgomp --without-newlib --disable-libstdcxx-pch --disable-threads \
        --disable-win32-registry --enable-lto --enable-plugin --disable-sjlj-exceptions \
        --enable-ssp --enable-libssp --disable-decimal-float --disable-nls \
        --with-sysroot=$PREFIX/$TARGET/sys-root --enable-languages=c,c++,lto >/dev/null && \
    make -j"$(nproc)" >/dev/null && make install-strip >/dev/null && \
    find $PREFIX/$TARGET $PREFIX/lib/gcc -name "*.a" -exec $TARGET-strip -S -x {} \; -exec $TARGET-ranlib {} \; && \
    mkdir -p $PREFIX/lib/bfd-plugins && \
    ln -sf ../gcc/$TARGET/14/liblto_plugin.so $PREFIX/lib/bfd-plugins/liblto_plugin_mintelf.so.14

# mintbin (stack, flags, ...)
RUN cd mintbin-0.4 && ./configure --prefix=$PREFIX --disable-nls --target=$TARGET >/dev/null && \
    make -j"$(nproc)" >/dev/null && make install >/dev/null && \
    strip $PREFIX/bin/* $PREFIX/$TARGET/bin/* 2>/dev/null; \
    $PREFIX/bin/$TARGET-gcc --version | head -1

FROM scratch
COPY --from=build /opt/cross-mint /opt/cross-mint
