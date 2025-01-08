/*
Copyright 2024.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package e2e

import (
	"fmt"
	"os/exec"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"

	"renku_pack_builder/test/utils"
)

var _ = Describe("controller", Ordered, func() {
	BeforeAll(func() {
		By("setting up Shipwright resources")
		Expect(utils.CreateShipwrightResources()).To(Succeed())
	})

	AfterAll(func() {
		By("remove Shipwright resources")
		Expect(utils.DeleteShipwrightResources()).To(Succeed())
	})

	Context("Builder", func() {
		It("should run successfully", func() {
			By("building the manager(Operator) image")
			cmd := exec.Command("make", "docker-build")
			_, err := utils.Run(cmd)
			ExpectWithOffset(1, err).NotTo(HaveOccurred())

			By("loading the builder image into the k3d cluster")
			cmd = exec.Command("make", "k3d-upload")
			_, err = utils.Run(cmd)
			ExpectWithOffset(1, err).NotTo(HaveOccurred())

			By("triggering the build run")
			projectDir, _ := utils.GetProjectDir()
			cmd = exec.Command("kubectl", "apply", "-f", projectDir+"/manifests/buildrun.yaml")
			_, err = utils.Run(cmd)
			ExpectWithOffset(1, err).NotTo(HaveOccurred())

			By("validating that the build run happened successfully")
			verifyBuildRun := func() error {
				cmd = exec.Command("kubectl", "get",
					"buildrun", "buildpack-python-env-3",
					"-o", "jsonpath={.status.conditions[0]['reason']}",
				)

				buildrunOutput, err := utils.Run(cmd)
				ExpectWithOffset(2, err).NotTo(HaveOccurred())
				conditions := utils.GetNonEmptyLines(string(buildrunOutput))
				if len(conditions) == 0 {
					return fmt.Errorf("failed to get conditions")
				}
				if conditions[0] != "Succeeded" {
					return fmt.Errorf("expected Succeed but got %v", conditions[0])
				}
				return nil
			}
			EventuallyWithOffset(1, verifyBuildRun, time.Minute, time.Second).Should(Succeed())
			cmd = exec.Command("kubectl", "delete", "-f", projectDir+"/manifests/buildrun.yaml")
			_, err = utils.Run(cmd)
			ExpectWithOffset(1, err).NotTo(HaveOccurred())

		})
	})
})
