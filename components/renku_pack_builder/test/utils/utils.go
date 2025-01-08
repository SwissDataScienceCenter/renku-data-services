package utils

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	. "github.com/onsi/ginkgo/v2" //nolint:golint,revive
)

const ()

func warnError(err error) {
	fmt.Fprintf(GinkgoWriter, "warning: %v\n", err)
}

// CreateShipwrightResources creates the Shipwright strategy and build.
func CreateShipwrightResources() error {
	projectDir, _ := GetProjectDir()
	cmd := exec.Command("kubectl", "apply", "-f", projectDir+"/manifests/buildstrategy_buildpacks.yaml")
	_, err := Run(cmd)
	if err != nil {
		return err
	}

	cmd = exec.Command("kubectl", "apply", "-f", projectDir+"/manifests/build.yaml")
	_, err = Run(cmd)
	return err
}

// DeleteShipwrightResources removes the Shipwright strategy and build.
func DeleteShipwrightResources() error {
	projectDir, _ := GetProjectDir()
	cmd := exec.Command("kubectl", "delete", "--ignore-not-found", "-f", projectDir+"/manifests/build.yaml")
	_, err := Run(cmd)
	if err != nil {
		return err
	}

	cmd = exec.Command("kubectl", "delete", "--ignore-not-found", "-f", projectDir+"/manifests/buildstrategy_buildpacks.yaml")
	_, err = Run(cmd)
	return err
}

// Run executes the provided command within this context
func Run(cmd *exec.Cmd) ([]byte, error) {
	dir, _ := GetProjectDir()
	cmd.Dir = dir

	if err := os.Chdir(cmd.Dir); err != nil {
		fmt.Fprintf(GinkgoWriter, "chdir dir: %s\n", err)
	}

	cmd.Env = append(os.Environ(), "GO111MODULE=on")
	command := strings.Join(cmd.Args, " ")
	fmt.Fprintf(GinkgoWriter, "running: %s\n", command)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return output, fmt.Errorf("%s failed with error: (%v) %s", command, err, string(output))
	}

	return output, nil
}

// GetNonEmptyLines converts given command output string into individual objects
// according to line breakers, and ignores the empty elements in it.
func GetNonEmptyLines(output string) []string {
	var res []string
	elements := strings.Split(output, "\n")
	for _, element := range elements {
		if element != "" {
			res = append(res, element)
		}
	}

	return res
}

// GetProjectDir will return the directory where the project is
func GetProjectDir() (string, error) {
	wd, err := os.Getwd()
	if err != nil {
		return wd, err
	}
	wd = strings.Replace(wd, "/test/e2e", "", -1)
	return wd, nil
}
