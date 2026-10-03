#!/bin/sh
# Small Gradle bootstrapper. It downloads the pinned Gradle distribution on first use,
# so a checked-in wrapper JAR is not required.
set -eu

APP_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GRADLE_VERSION=8.9
USER_HOME=${GRADLE_USER_HOME:-"${HOME:-.}/.gradle"}
DIST_ROOT="$USER_HOME/wrapper/dists/gradle-${GRADLE_VERSION}-bin/universal-text-extractor"
GRADLE_HOME="$DIST_ROOT/gradle-${GRADLE_VERSION}"
GRADLE_BIN="$GRADLE_HOME/bin/gradle"

if [ ! -x "$GRADLE_BIN" ]; then
    mkdir -p "$DIST_ROOT"
    ZIP_FILE="$DIST_ROOT/gradle-${GRADLE_VERSION}-bin-$$.zip"
    URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
    echo "Downloading Gradle ${GRADLE_VERSION}..."
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 "$URL" -o "$ZIP_FILE"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$ZIP_FILE" "$URL"
    else
        echo "curl or wget is required to download Gradle ${GRADLE_VERSION}." >&2
        exit 1
    fi
    if ! command -v unzip >/dev/null 2>&1; then
        echo "unzip is required to unpack Gradle ${GRADLE_VERSION}." >&2
        rm -f "$ZIP_FILE"
        exit 1
    fi
    unzip -q -o "$ZIP_FILE" -d "$DIST_ROOT"
    rm -f "$ZIP_FILE"
fi

exec "$GRADLE_BIN" -p "$APP_HOME" "$@"
