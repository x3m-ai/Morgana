// cmd.exe executor - Windows only
package executor

import (
	"bytes"
	"context"
	"os/exec"
	"strings"
)

func runCmd(ctx context.Context, command string) (*Result, error) {
	// Join multi-line commands with " & " so cmd.exe executes them in sequence
	// within the same shell process (preserving cd, env vars, etc.)
	normalized := strings.ReplaceAll(command, "\r\n", "\n")
	lines := strings.Split(normalized, "\n")
	var nonEmpty []string
	for _, l := range lines {
		if strings.TrimSpace(l) != "" {
			nonEmpty = append(nonEmpty, l)
		}
	}
	script := strings.Join(nonEmpty, " & ")

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, "cmd.exe", "/C", script)
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
