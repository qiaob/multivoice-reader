#!/bin/sh
# Put the llama.cpp source the app is built with in android/third_party/llama.cpp.
#
# It is taken from the llama-cpp-python source package on PyPI, which carries a whole copy of
# llama.cpp, pinned here so every build uses the same one.
set -eu
VERSION=0.3.37
HERE=$(cd "$(dirname "$0")/.." && pwd)
DEST="$HERE/third_party/llama.cpp"
[ -f "$DEST/.from-llama-cpp-python-$VERSION" ] && exit 0
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
python3 -m pip download --quiet --no-deps --no-binary :all: "llama-cpp-python==$VERSION" -d "$WORK"
tar -xzf "$WORK"/llama_cpp_python-$VERSION.tar.gz -C "$WORK"
rm -rf "$DEST"
mkdir -p "$HERE/third_party"
mv "$WORK/llama_cpp_python-$VERSION/vendor/llama.cpp" "$DEST"
rm -f "$DEST/.git"  # a pointer to the submodule it was in, which is not here
touch "$DEST/.from-llama-cpp-python-$VERSION"
echo "llama.cpp from llama-cpp-python $VERSION is in $DEST"
