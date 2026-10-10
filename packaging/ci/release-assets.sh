#!/bin/sh
# Collects a release: the six packages, SHA256SUMS and the release notes.
#   packaging/ci/release-assets.sh <version> <owner/repo> <directory with packages> <output dir> <notes file>
set -eu
version=$1 repo=$2 in=$3 out=$4 notes=$5
cd "$(dirname "$0")/../.."
mkdir -p "$out"
find "$in" -type f \( -name '*.deb' -o -name '*.rpm' -o -name '*.pkg.tar.zst' \) -exec cp {} "$out"/ \;
for f in "mothership_${version}_all.deb" "mothership-dkms_${version}_all.deb" \
         "mothership-${version}-1.noarch.rpm" "mothership-dkms-${version}-1.noarch.rpm"; do
  [ -f "$out/$f" ] || { echo "release-assets: missing $f" >&2; exit 1; }
done
set -- "$out"/mothership-[0-9]*-any.pkg.tar.zst
[ $# = 1 ] && [ -f "$1" ] || { echo "release-assets: expected one mothership Arch package" >&2; exit 1; }
archver=${1##*/mothership-}; archver=${archver%-any.pkg.tar.zst}
[ -f "$out/mothership-dkms-$archver-any.pkg.tar.zst" ] || { echo "release-assets: missing mothership-dkms-$archver-any.pkg.tar.zst" >&2; exit 1; }
[ "$(ls "$out" | wc -l)" = 6 ] || { echo "release-assets: expected 6 packages in $out" >&2; ls -l "$out" >&2; exit 1; }
(cd "$out" && sha256sum -- * > SHA256SUMS)
# "What's new": this version's section of CHANGELOG.md (a pre-release like 0.1.2-rc1 uses 0.1.2's).
base=${version%%-*}
changes=$(awk -v v="$base" '/^## / { on = (index($0, "## " v " ") == 1 || $0 == "## " v) ; next } on' CHANGELOG.md)
{
  if [ -n "$changes" ]; then
    printf "## What's new\n%s\n\n" "$changes"
  fi
  sed -e "s|@VERSION@|$version|g" -e "s|@REPO@|$repo|g" -e "s|@ARCHVER@|$archver|g" packaging/release-notes.md
} > "$notes"
cat "$out/SHA256SUMS"
