def main():
    patches = []
    # patches.append(
    #     {
    #         "type": "application/json-patch+json",
    #         "patch": [
    #             {
    #                 "op": "add",
    #                 "path": "/statefulset/spec/template/spec/containers/-",
    #                 "value": {
    #                     "image": current_app.config["GIT_RPC_SERVER_IMAGE"],
    #                     "name": "git-sidecar",
    #                     # Do not expose this until access control is in place
    #                     # "ports": [
    #                     #     {
    #                     #         "containerPort": 4000,
    #                     #         "name": "git-port",
    #                     #         "protocol": "TCP",
    #                     #     }
    #                     # ],
    #                     "env": [
    #                         {
    #                             "name": "MOUNT_PATH",
    #                             "value": f"/work/{self.gl_project.path}",
    #                         }
    #                     ],
    #                     "resources": {},
    #                     "securityContext": {
    #                         "allowPrivilegeEscalation": False,
    #                         "fsGroup": 100,
    #                         "runAsGroup": 100,
    #                         "runAsUser": 1000,
    #                     },
    #                     "volumeMounts": [
    #                         {
    #                             "mountPath": f"/work/{self.gl_project.path}/",
    #                             "name": "workspace",
    #                             "subPath": f"{self.gl_project.path}/",
    #                         }
    #                     ],
    #                     # Enable readiness and liveness only when control is in place
    #                     # "livenessProbe": {
    #                     #     "httpGet": {"port": 4000, "path": "/"},
    #                     #     "periodSeconds": 30,
    #                     #     # delay should equal periodSeconds x failureThreshold
    #                     #     # from readiness probe values
    #                     #     "initialDelaySeconds": 600,
    #                     # },
    #                     # the readiness probe will retry 36 times over 360 seconds to see
    #                     # if the pod is ready to accept traffic - this gives the user session
    #                     # a maximum of 360 seconds to setup the git sidecar and clone the repo
    #                     # "readinessProbe": {
    #                     #     "httpGet": {"port": 4000, "path": "/"},
    #                     #     "periodSeconds": 10,
    #                     #     "failureThreshold": 60,
    #                     # },
    #                 },
    #             }
    #         ],
    #     }
    # )
    # We can add this to expose the git side-car once it's protected.
    # patches.append(
    #     {
    #         "type": "application/json-patch+json",
    #         "patch": [
    #             {
    #                 "op": "add",
    #                 "path": "/service/spec/ports/-",
    #                 "value": {
    #                     "name": "git-service",
    #                     "port": 4000,
    #                     "protocol": "TCP",
    #                     "targetPort": 4000,
    #                 },
    #             }
    #         ],
    #     }
    # )
    return patches
