// PowerShell executor - Windows (powershell.exe) and Linux/macOS (pwsh)
package executor

import (
	"bytes"
	"context"
	"os/exec"
	"runtime"
)

func runPowerShell(ctx context.Context, command string) (*Result, error) {
	var psExe string
	if runtime.GOOS == "windows" {
		psExe = "powershell.exe"
	} else {
		// PowerShell Core on Linux/macOS
		psExe = "pwsh"
	}

	args := []string{
		"-NoProfile",
		"-NonInteractive",
		"-ExecutionPolicy", "Bypass",
		"-Command", command,
	}

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, psExe, args...)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
			err = nil // Non-zero exit is not a Go error, it's a result
		} else {
			return nil, err
		}
	}

	stdoutStr, stderrStr := captureOutput(&stdout, &stderr)
	return &Result{
		ExitCode: exitCode,
		Stdout:   stdoutStr,
		Stderr:   stderrStr,
	}, err
}
