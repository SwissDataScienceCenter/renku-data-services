if [ "${K3D_VERSION}" != "none" ]; then
    echo "Downloading k3d..."
    if [ "${K3D_VERSION}" = "latest" ]; then
        # Install and check the hash
        curl -sSL https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
    else
        find_version_from_git_tags K3D_VERSION https://github.com/kubernetes/K3D
        if [ "${K3D_VERSION::1}" != "v" ]; then
            K3D_VERSION="v${K3D_VERSION}"
        fi
        # Install and check the hash
        curl -sSL https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG="${K3D_VERSION}" bash
    fi
fi
