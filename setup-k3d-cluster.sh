#!/usr/bin/env bash

KPACK_VERSION=0.15.0
INTERNL_RE="host\.k3d\.internal"
REGISTRY_NAME="kpack-registry.local"
REGISTRY_PORT=5000
REGISTRY_URI=$REGISTRY_NAME:$REGISTRY_PORT
K3D_REGISTRY_NAME="k3d-$REGISTRY_NAME"

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

function setup_kpack() {
    # deploy kpack
    kubectl apply -f https://github.com/buildpacks-community/kpack/releases/download/v$KPACK_VERSION/release-$KPACK_VERSION.yaml
    kubectl --namespace kpack wait deployments.apps/kpack-controller --for='jsonpath={.status.conditions[?(@.type=="Available")].status}=True'

    # create kpack resources
    kubectl apply -f .devcontainer/kpack/clusterstore.yaml
    kubectl wait --for=condition=Ready=True clusterstores.kpack.io/default
    kubectl apply -f .devcontainer/kpack/clusterstack.yaml
    kubectl wait --for=condition=Ready=True clusterstack.kpack.io/base
    kubectl apply -f .devcontainer/kpack/python-builder.yaml

    # Fails sometimes because it seems some things happens a bit too fast and it
    # looks like the reconciler does not retry to reconcile the builder.
    # Recreating it fixes the situation
    set +e
    kubectl wait --for=condition=Ready=True builder.kpack.io/python-builder
    if [[ $? -eq 1 ]]
    then
        kubectl delete -f builder.yaml
        kubectl apply -f builder.yaml
    fi
    set -e
    kubectl wait --for=condition=Ready=True builder.kpack.io/python-builder
}

deploy_kpack=false
create_image=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --deploy-kpack)
            deploy_kpack=true
            shift # past value
            ;;
        --create-image)
            create_image=true
            shift # past value
            ;;
        -*|--*)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

setup_registry

set -e
k3d cluster create kpack-test --registry-use $K3D_REGISTRY_NAME:$REGISTRY_PORT --registry-config registries.yaml --agents 1 --k3s-arg --disable=metrics-server@server:0

setup_dns
copy_image

if [[ $deploy_kpack == true ]]
then
    setup_kpack
fi

if [[ $create_image == true ]]
then
    kubectl apply -f image.yaml
fi
