// Package executor handles script execution for the Morgana Agent.
// It dispatches to the appropriate executor (PowerShell, cmd, bash, python).
package executor

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/x3m-ai/morgana-agent/internal/config"
)

// Result holds the output of an executed command.
type Result struct {
	ExitCode int
	Stdout   string
	Stderr   string
}

// Dispatcher selects and runs the appropriate executor for a given job.
type Dispatcher struct {
	cfg    *config.Config
	client *http.Client
}

// NewDispatcher creates a new Dispatcher.
func NewDispatcher(cfg *config.Config) *Dispatcher {
	return &Dispatcher{
		cfg:    cfg,
		client: cfg.HTTPClient(),
	}
}

// Execute runs a command using the specified executor within the given timeout.
func (d *Dispatcher) Execute(executorName string, command string, timeout time.Duration) (*Result, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	switch strings.ToLower(executorName) {
	case "powershell":
		return runPowerShell(ctx, command)
	case "cmd", "command_prompt":
		if runtime.GOOS != "windows" {
			return nil, fmt.Errorf("cmd executor is Windows-only")
		}
		return runCmd(ctx, command)
	case "bash", "sh":
		return runBash(ctx, command)
	case "python":
		return runPython(ctx, command)
	case "manual":
		return &Result{ExitCode: 0, Stdout: "[MANUAL] This test requires manual execution."}, nil
	default:
		return nil, fmt.Errorf("unknown executor: %s", executorName)
	}
}

// ResolveInputArgs replaces #{arg_name} placeholders in the command with actual values.
func (d *Dispatcher) ResolveInputArgs(command string, args map[string]any) string {
	if len(args) == 0 {
		return command
	}
	result := command
	for k, v := range args {
		placeholder := fmt.Sprintf("#{%s}", k)
		value := fmt.Sprintf("%v", v)
		result = strings.ReplaceAll(result, placeholder, value)
	}
	return result
}

// DownloadPayload downloads a file from the URL to the work directory.
// Returns the local path where the file was saved.
func (d *Dispatcher) DownloadPayload(url string, testID string) (string, error) {
	dir := filepath.Join(d.cfg.WorkDir, testID)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", fmt.Errorf("cannot create work dir %s: %w", dir, err)
	}

	filename := filepath.Base(url)
	if filename == "" || filename == "." {
		filename = "payload"
	}
	outPath := filepath.Join(dir, filename)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", err
	}

	resp, err := d.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("download failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("download returned HTTP %d", resp.StatusCode)
	}

	f, err := os.Create(outPath)
	if err != nil {
		return "", fmt.Errorf("cannot create payload file: %w", err)
	}
	defer f.Close()

	if _, err := io.Copy(f, resp.Body); err != nil {
		return "", fmt.Errorf("write payload: %w", err)
	}

	return outPath, nil
}

// captureOutput reads all of stdout and stderr from the buffers into strings.
func captureOutput(stdout, stderr *bytes.Buffer) (string, string) {
	return stdout.String(), stderr.String()
}
