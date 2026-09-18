#!/bin/sh
# Kept as the image's ENTRYPOINT so there is one place to add startup logic, but
# it deliberately does nothing conditional.
#
# `migrate` and `collectstatic` used to run here. They now run in the one-shot
# `init` service in docker-compose.yml, because `web`, `worker` and `beat` share
# this image: three containers would otherwise run `migrate` concurrently against
# one SQLite file (which `migrate` has never supported) and race each other on
# `collectstatic --clear` into one shared volume. A crash-looping container also
# re-ran migrations on every restart, which turns a bad migration into a loop
# rather than a failed deploy.
set -eu

exec "$@"
