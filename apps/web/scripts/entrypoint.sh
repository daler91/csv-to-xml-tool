#!/bin/sh
# Web container entrypoint: make DATA_DIR writable, then run the app as `node`.
#
# The image chowns /data to `node` at build time, but a volume mounted over it
# at runtime keeps its own ownership. Railway mounts volumes root-owned, and
# that is not configurable; a volume first used while this image still ran as
# root (before 6fad498) holds root-owned uploads/ and output/ directories.
# Either way `node` cannot write there: every upload failed with EACCES, which
# the browser shows as "Something went wrong on our side".
#
# So the container starts as root only long enough to re-own DATA_DIR, then
# su-exec replaces this shell with the command running as `node`. No root
# process stays behind, and migrate.js and server.js never run as root.
set -eu

DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
  # Only entries that are not node's already, so a volume full of uploads is
  # not rewritten on every boot. -h re-owns a symlink itself, never its target,
  # and a file with more than one hard link is left alone: the app never makes
  # one, and re-owning it would re-own its other names too, wherever they are.
  # A failure here is reported, not fatal -- the app still serves everything
  # but uploads, as it did before this script existed.
  if ! { mkdir -p "$DATA_DIR" &&
    find "$DATA_DIR" ! -user node \( -type d -o -links 1 \) \
      -exec chown -h node:node {} +; }; then
    echo "entrypoint: could not give $DATA_DIR to user node; uploads will fail with EACCES" >&2
  fi
  exec su-exec node "$@"
fi

# Started as some other user (docker run --user, a non-zero RAILWAY_RUN_UID, a
# platform that forces one): nothing can be re-owned from here, so say why
# uploads will fail rather than leave it to a bare 500 at the first one.
for dir in "$DATA_DIR" "$DATA_DIR/uploads" "$DATA_DIR/output"; do
  if [ -e "$dir" ] && [ ! -w "$dir" ]; then
    echo "entrypoint: $dir is not writable by uid $(id -u); uploads will fail with EACCES" >&2
  fi
done
exec "$@"
