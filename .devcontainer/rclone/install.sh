#!/bin/bash

set -ex

echo "Downloading rclone sources from ${RCLONE_REPOSITORY}:${RCLONE_REF}"
mkdir -p /tmp/rclone
cd /tmp/rclone
git clone "${RCLONE_REPOSITORY}"
cd rclone
git checkout "${RCLONE_REF}"

echo "Building rclone"
make rclone
cd $HOME
rm -rf /tmp/rclone
