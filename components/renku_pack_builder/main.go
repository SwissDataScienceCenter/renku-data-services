package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"slices"
	"strings"
)

const (
	envDir    string = "/platform/env"
	layersDir string = "/tmp/.shp/layers"
	cacheDir  string = "/tmp/.shp/cache"

	paramOutputImageKey   string = "PARAM_OUTPUT_IMAGE"
	paramSourceContextKey string = "PARAM_SOURCE_CONTEXT"
)

var (
	blockList = []string{"PATH", "HOSTNAME", "PWD", "_", "SHLVL", "HOME", ""}
	Version   = "dev"
)

func checkError(err error) {
	if err != nil {
		panic(err)
	}
}

func checkCmdError(err error, output []byte) {
	if err != nil {
		fmt.Println(string(output))
		panic(err)
	}
}

func announcePhase(msg string) {
	fmt.Println("===> ", msg)
}

func main() {
	paramOutputImage := ""
	paramSourceContext := ""

	for _, e := range os.Environ() {
		pair := strings.SplitN(e, "=", 2)
		key := pair[0]
		value := pair[1]

		if slices.Contains(blockList, key) {
			continue
		}

		if key == paramOutputImageKey {
			paramOutputImage = value
		} else if key == paramSourceContextKey {
			paramSourceContext = value
		}

		path := envDir + "/" + key
		f, err := os.Create(path)
		checkError(err)
		_, err = f.WriteString(value)
		f.Close()
		checkError(err)
	}

	if paramOutputImage == "" {
		panic("missing or empty PARAM_OUTPUT_IMAGE")
	}

	if paramSourceContext == "" {
		panic("missing or empty PARAM_SOURCE_CONTEXT")
	}

	err := os.MkdirAll(layersDir, 0777)
	checkError(err)
	err = os.Mkdir(cacheDir, 0777)
	checkError(err)

	announcePhase("ANALYZING")
	cmd := exec.Command("/cnb/lifecycle/analyzer", "-layers="+layersDir, paramOutputImage)
	out, err := cmd.Output()
	checkCmdError(err, out)

	announcePhase("DETECTING")
	cmd = exec.Command("/cnb/lifecycle/detector", "-app="+paramSourceContext, "-layers="+layersDir)
	out, err = cmd.Output()
	checkCmdError(err, out)

	announcePhase("RESTORING")
	cmd = exec.Command("/cnb/lifecycle/restorer", "-cache-dir="+cacheDir, "-layers="+layersDir)
	out, err = cmd.Output()
	checkCmdError(err, out)

	announcePhase("BUILDING")
	cmd = exec.Command("/cnb/lifecycle/builder", "-app="+paramSourceContext, "-layers="+layersDir)
	out, err = cmd.Output()
	checkCmdError(err, out)

	announcePhase("EXPORTING")
	exporterArgs := []string{"-layers=" + layersDir, "-report=/tmp/report.toml", "-cache-dir=" + cacheDir, "-app=" + paramSourceContext}

	f, err := os.Open(layersDir + "/config/metadata.toml")
	checkError(err)
	defer f.Close()

	data, err := io.ReadAll(f)
	checkError(err)

	if !strings.Contains(string(data), "buildpack-default-process-type") {
		exporterArgs = append(exporterArgs, "-process-type=web")
	}

	exporterArgs = append(exporterArgs, paramOutputImage)

	cmd = exec.Command("/cnb/lifecycle/exporter", exporterArgs...)
	out, err = cmd.CombinedOutput()
	checkCmdError(err, out)

	f, err = os.Open("/tmp/report.toml")
	checkError(err)

	fileScanner := bufio.NewScanner(f)
	fileScanner.Split(bufio.ScanLines)
	var fileLines []string

	for fileScanner.Scan() {
		fileLines = append(fileLines, fileScanner.Text())
	}

	f.Close()

	imageDigest := ""
	for _, line := range slices.Backward(fileLines) {
		if strings.Contains(line, "digest=") {
			pairs := strings.SplitN(line, "=", 2)
			imageDigest = pairs[1]
			break
		}
	}

	imageDigestFilePath := os.Args[1]
	f, err = os.Create(imageDigestFilePath)
	checkError(err)
	defer f.Close()
	_, err = f.WriteString(imageDigest)
	checkError(err)
	announcePhase("DONE")
}
