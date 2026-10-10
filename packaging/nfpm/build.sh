#!/bin/sh
# Builds the mothership and mothership-dkms .deb and .rpm packages with nFPM.
#   packaging/nfpm/build.sh [VERSION] [OUTDIR]
# VERSION defaults to mothership/__init__.py's, OUTDIR to dist/. NFPM=/path/to/nfpm picks nfpm.
set -eu
cd "$(dirname "$0")/../.."
version=${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' mothership/__init__.py)}
out=${2:-dist}
nfpm=${NFPM:-nfpm}
case "$version" in
  [0-9]*) ;;
  *) echo "build.sh: bad version '$version'" >&2; exit 1 ;;
esac
if printf '%s' "$version" | grep -q '[^0-9A-Za-z.+~-]'; then
  echo "build.sh: bad version '$version'" >&2; exit 1
fi

stage=build/nfpm
rm -rf "$stage"
make -s install LAYOUT=private COMPILE=0 PREFIX=/usr DESTDIR="$PWD/$stage/mothership" >/dev/null
make -s install-dkms PREFIX=/usr DESTDIR="$PWD/$stage/dkms" VERSION="$version" >/dev/null
mkdir -p "$stage/scripts" "$out"
for f in packaging/nfpm/scripts/*; do
  sed "s/@VERSION@/$version/g" "$f" > "$stage/scripts/${f##*/}"
  chmod 755 "$stage/scripts/${f##*/}"
done

# nFPM expands variables in a few fields only (not in contents), so substitute them here.
for pkg in mothership mothership-dkms; do
  sed 's/${MOTHERSHIP_VERSION}/'"$version"'/g' "packaging/nfpm/$pkg.yaml" > "$stage/$pkg.yaml"
done
"$nfpm" package -f "$stage/mothership.yaml" -p deb -t "$out/mothership_${version}_all.deb"
"$nfpm" package -f "$stage/mothership-dkms.yaml" -p deb -t "$out/mothership-dkms_${version}_all.deb"
"$nfpm" package -f "$stage/mothership.yaml" -p rpm -t "$out/mothership-${version}-1.noarch.rpm"
"$nfpm" package -f "$stage/mothership-dkms.yaml" -p rpm -t "$out/mothership-dkms-${version}-1.noarch.rpm"
