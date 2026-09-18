#!/bin/bash

# dockerd registers its bridge driver through iptables. With the legacy backend that fails
# on hosts whose kernel provides no ip_tables module:
#
#   iptables v1.8.11 (legacy): can't initialize iptables table `nat': Table does not exist
#
# The daemon then never starts, and `kind` cannot create the cluster the tests need. This
# installs after the docker-in-docker feature, which is what puts iptables in the image, and
# before the first container boot, which is when that feature's docker-init.sh starts dockerd.

set -ex

if [ ! -x /usr/sbin/iptables-nft ]; then
    echo "iptables-nft is not present, leaving the alternatives alone."
    exit 0
fi

update-alternatives --set iptables /usr/sbin/iptables-nft
update-alternatives --set ip6tables /usr/sbin/ip6tables-nft
