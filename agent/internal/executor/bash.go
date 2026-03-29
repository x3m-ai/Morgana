// bash/sh executor - Linux and macOS
package executor

import (
	"bytes"
	"context"
	"os/exec"
)

func runBash(ctx context.Context, command string) (*Result, error) {
	shell := "/bin/bash"
	if _, err := exec.LookPath("/bin/bash"); err != nil {
		shell = "/bin/sh"
	}

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, shell, "-c", command)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
			err = nil
		} else {
			return nil, err
		}
	}

	stdoutStr, stderrStr := captureOutput(&stdout, &stderr)
	return &Result{ExitCode: exitCode, Stdout: stdoutStr, Stderr: stderrStr}, err
}

func runPython(ctx context.Context, command string) (*Result, error) {
	python := "python3"
	if _, err := exec.LookPath("python3"); err != nil {
		python = "python"
	}

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, python, "-c", command)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
			err = nil
		} else {
			return nil, err
		}
	}

	stdoutStr, stderrStr := captureOutput(&stdout, &stderr)
	return &Result{ExitCode: exitCode, Stdout: stdoutStr, Stderr: stderrStr}, err
}
