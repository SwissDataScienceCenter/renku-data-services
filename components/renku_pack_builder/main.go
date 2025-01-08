package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"

	"github.com/go-cmd/cmd"
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

func runCommand(command string, args ...string) {
	cmdOptions := cmd.Options{
		Buffered:  false,
		Streaming: true,
	}

	runCmd := cmd.NewCmdOptions(cmdOptions, command, args...)

	// Print STDOUT and STDERR lines streaming from Cmd
	doneChan := make(chan struct{})
	go func() {
		defer close(doneChan)
		// Done when both channels have been closed
		// https://dave.cheney.net/2013/04/30/curious-channels
		for runCmd.Stdout != nil || runCmd.Stderr != nil {
			select {
			case line, open := <-runCmd.Stdout:
				if !open {
					runCmd.Stdout = nil
					continue
				}
				fmt.Println(line)
			case line, open := <-runCmd.Stderr:
				if !open {
					runCmd.Stderr = nil
					continue
				}
				fmt.Fprintln(os.Stderr, line)
			}
		}
	}()

	// Run and wait for Cmd to return, discard Status
	status := <-runCmd.Start()

	// Wait for goroutine to print everything
	<-doneChan

	if status.Error != nil {
		fmt.Println(status.Stderr)
		panic(status.Error)
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
		panic("missing or empty PARAM_OUTPUT_IMAGE environment variable")
	}

	if paramSourceContext == "" {
		panic("missing or empty PARAM_SOURCE_CONTEXT environment variable")
	}

	err := os.MkdirAll(layersDir, 0777)
	checkError(err)
	err = os.Mkdir(cacheDir, 0777)
	checkError(err)

	announcePhase("ANALYZING")
	runCommand("/cnb/lifecycle/analyzer", "-layers="+layersDir, paramOutputImage)

	announcePhase("DETECTING")
	runCommand("/cnb/lifecycle/detector", "-app="+paramSourceContext, "-layers="+layersDir)

	announcePhase("RESTORING")
	runCommand("/cnb/lifecycle/restorer", "-cache-dir="+cacheDir, "-layers="+layersDir)

	announcePhase("BUILDING")
	runCommand("/cnb/lifecycle/builder", "-app="+paramSourceContext, "-layers="+layersDir)

	announcePhase("EXPORTING")

	f, err := os.Open(layersDir + "/config/metadata.toml")
	checkError(err)
	data, err := io.ReadAll(f)
	checkError(err)
	f.Close()

	exporterArgs := []string{"-layers=" + layersDir, "-report=/tmp/report.toml", "-cache-dir=" + cacheDir, "-app=" + paramSourceContext}
	if !strings.Contains(string(data), "buildpack-default-process-type") {
		exporterArgs = append(exporterArgs, "-process-type=web")
	}
	exporterArgs = append(exporterArgs, paramOutputImage)

	runCommand("/cnb/lifecycle/exporter", exporterArgs...)

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
