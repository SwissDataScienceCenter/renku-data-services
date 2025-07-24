#!/usr/bin/env bash

SHIPWRIGHT_VERSION=v0.14.0
INTERNL_RE="host\.k3d\.internal"
REGISTRY_NAME="dev-registry.local"
REGISTRY_PORT=5000
REGISTRY_URI=$REGISTRY_NAME:$REGISTRY_PORT
K3D_REGISTRY_NAME="k3d-$REGISTRY_NAME"
CLUSTER_NAME="devel"

function delete_all() {
    k3d cluster delete $CLUSTER_NAME
    k3d registry delete $REGISTRY_NAME
}

function setup_registry() {
    set +e
    registry=$(k3d registry list | grep $REGISTRY_NAME)

    set -e

    if [[ "$registry" == "" ]]
    then
        echo "Creating registry $REGISTRY_URI"
        k3d registry create $REGISTRY_NAME -p $REGISTRY_PORT
    else
        echo "Registry $REGISTRY_NAME already exist -> reusing."
    fi
}

function setup_cluster() {
    set +e
    cluster=$(k3d cluster list | grep $CLUSTER_NAME)

    set -e

    if [[ "$cluster" == "" ]]
    then
        echo "Creating cluster $CLUSTER_NAME"
        k3d cluster create $CLUSTER_NAME --registry-use $K3D_REGISTRY_NAME:$REGISTRY_PORT --registry-config registries.yaml --agents 1 --k3s-arg --disable=metrics-server@server:0
    else
        echo "Cluster $CLUSTER_NAME already exist -> reusing."
    fi
}

function setup_dns() {
    echo "Updating the cluster DNS configuration to make the registry accessible"

    # Wait for the DNS to contain the internal entry
    internal_added=false

    until [ $internal_added == true ]
    do

        configmap=$(kubectl get configmaps --namespace kube-system coredns -o yaml)
        if [[ $configmap =~ $INTERNL_RE ]]
        then
            internal_added=true
        fi
    done

    # Add entry to the DNS so that the API of the registry can be accessed
    kubectl get configmaps --namespace kube-system coredns -o yaml | sed -e "s/\(host.k3d.internal\)/\\1 $REGISTRY_NAME/g" | kubectl apply -f -
    # Restart the coredns pod to take into account the config change
    coredns_pod=$(kubectl --namespace kube-system get pods | grep coredns | awk '{print $1}')
    kubectl --namespace kube-system delete pod "$coredns_pod" --wait=true
    # Wait for the pod to be back on track
    coredns_pod=$(kubectl --namespace kube-system get pods | grep coredns | awk '{print $1}')
    kubectl --namespace kube-system wait --for=condition=Ready "pod/$coredns_pod"
}

function copy_image() {
    # copy image to registry
    echo "Copying image from source registry to $REGISTRY_URI"
    kubectl create job copy-image --image quay.io/skopeo/stable:latest -- skopeo copy docker://paketobuildpacks/builder-jammy-base:latest docker://$REGISTRY_URI/paketobuildpacks/builder-jammy-base:latest --dest-tls-verify=false
    kubectl wait --for=condition=complete job/copy-image
    kubectl delete job copy-image
}

function setup_shipwright() {
    # Setup tekton
    curl --silent --location https://raw.githubusercontent.com/shipwright-io/build/$SHIPWRIGHT_VERSION/hack/install-tekton.sh | bash

    # Setup Shipwright
    kubectl apply --filename https://github.com/shipwright-io/build/releases/download/$SHIPWRIGHT_VERSION/release.yaml --server-side
    curl --silent --location https://raw.githubusercontent.com/shipwright-io/build/$SHIPWRIGHT_VERSION/hack/setup-webhook-cert.sh | bash
    curl --silent --location https://raw.githubusercontent.com/shipwright-io/build/main/hack/storage-version-migration.sh | bash

    # Install Shipwright strategies
    kubectl apply --filename https://github.com/shipwright-io/build/releases/download/$SHIPWRIGHT_VERSION/sample-strategies.yaml --server-side

    set -x
}

function test_shipwright_build() {
    cat <<EOF | kubectl apply -f -
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: buildpack-nodejs-build
spec:
  source:
    type: Git
    git:
      url: https://github.com/shipwright-io/sample-nodejs
    contextDir: source-build
  strategy:
    name: buildpacks-v3
    kind: ClusterBuildStrategy
  output:
    image: ${REGISTRY_URI}/sample-nodejs:latest
EOF
    cat <<EOF | kubectl create -f -
    apiVersion: shipwright.io/v1beta1
    kind: BuildRun
    metadata:
      generateName: buildpack-nodejs-buildrun-
    spec:
      build:
        name: buildpack-nodejs-build
EOF
}

reset=false
deploy_shipwright=false
create_image=false
test_build=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --reset)
            reset=true
            shift # past value
            ;;
        --deploy-shipwright)
            deploy_shipwright=true
            shift # past value
            ;;
        --create-image)
            create_image=true
            shift # past value
            ;;
        --test-build)
            test_build=true
            shift # past value
            ;;
        -*|--*)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

if [[ $reset == true ]]
then
    delete_all
fi

setup_registry
setup_cluster

setup_dns


if [[ $deploy_shipwright == true ]]
then
    setup_shipwright
fi

if [[ $create_image == true ]]
then
    kubectl apply -f image.yaml
fi

if [[ $test_build == true ]]
then
    test_shipwright_build
fi
