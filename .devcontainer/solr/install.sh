#!/bin/sh
set -e

echo "Activation SOLR feature"
download_url="https://archive.apache.org/dist/solr/solr/$SOLR_VERSION/solr-$SOLR_VERSION.tgz"

curl -sSL -o solr.tgz "$download_url"
mkdir -p /opt
tar -C /opt -xzf solr.tgz
ln -snf "/opt/solr-$SOLR_VERSION" /opt/solr
ln -snf /opt/solr/bin/solr /usr/local/bin/solr
mkdir -p /opt/solr/server/logs
chmod 777 /opt/solr/server/logs
chmod 777 /opt/solr/bin
chown -R vscode:vscode "/opt/solr-$SOLR_VERSION"
