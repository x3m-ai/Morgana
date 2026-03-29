// Package beacon implements the polling loop that connects the agent to the Morgana server.
package beacon

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/x3m-ai/morgana-agent/internal/config"
	"github.com/x3m-ai/morgana-agent/internal/executor"
	"github.com/x3m-ai/morgana-agent/internal/logger"
)

// Job represents a job dispatched from the server to this agent.
type Job struct {
	ID             string         `json:"id"`
	TestID         string         `json:"test_id"`
	Executor       string         `json:"executor"`
	Command        string         `json:"command"`
	CleanupCommand string         `json:"cleanup_command"`
	InputArgs      map[string]any `json:"input_args"`
	DownloadURL    string         `json:"download_url"`
	TimeoutSeconds int            `json:"timeout_seconds"`
	Signature      string         `json:"signature"`
}

// PollResponse is the server's response to a beacon poll.
type PollResponse struct {
	Job            *Job `json:"job"`
	BeaconInterval int  `json:"beacon_interval"`
}

// Beacon manages the agent polling loop.
type Beacon struct {
	cfg    *config.Config
	client *http.Client
	log    *logger.Logger
	exec   *executor.Dispatcher
}

// New creates a new Beacon.
func New(cfg *config.Config) *Beacon {
	return &Beacon{
		cfg:    cfg,
		client: cfg.HTTPClient(),
		log:    logger.New("morgana.beacon"),
		exec:   executor.NewDispatcher(cfg),
	}
}

// Run starts the polling loop. Blocks until ctx is cancelled.
func (b *Beacon) Run(ctx context.Context) error {
	b.log.Info("[BEACON] Starting beacon loop", map[string]any{
		"paw":      b.cfg.PAW,
		"server":   b.cfg.ServerURL,
		"interval": b.cfg.BeaconInterval,
	})

	interval := time.Duration(b.cfg.BeaconInterval) * time.Second
	lastHeartbeat := time.Time{}

	for {
		select {
		case <-ctx.Done():
			b.log.Info("[BEACON] Context cancelled, stopping", nil)
			return nil
		case <-time.After(interval):
		}

		// Send heartbeat every 60s
		if time.Since(lastHeartbeat) > 60*time.Second {
			b.sendHeartbeat()
			lastHeartbeat = time.Now()
		}

		// Poll for job
		resp, err := b.poll()
		if err != nil {
			b.log.Warn("[BEACON] Poll failed, will retry", map[string]any{"error": err.Error()})
			continue
		}

		// Update interval if server changed it
		if resp.BeaconInterval > 0 && resp.BeaconInterval != b.cfg.BeaconInterval {
			b.log.Info("[BEACON] Server updated beacon interval", map[string]any{"interval": resp.BeaconInterval})
			interval = time.Duration(resp.BeaconInterval) * time.Second
		}

		if resp.Job == nil {
			b.log.Debug("[BEACON] No jobs pending", nil)
			continue
		}

		// Execute job asynchronously so beacon keeps running
		go b.executeJob(resp.Job)
	}
}

func (b *Beacon) poll() (*PollResponse, error) {
	url := fmt.Sprintf("%s/api/v2/agent/poll?paw=%s", b.cfg.ServerURL, b.cfg.PAW)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+b.cfg.AgentToken)

	resp, err := b.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server returned %d", resp.StatusCode)
	}

	var pollResp PollResponse
	if err := json.NewDecoder(resp.Body).Decode(&pollResp); err != nil {
		return nil, fmt.Errorf("decode poll response: %w", err)
	}

	return &pollResp, nil
}

func (b *Beacon) executeJob(job *Job) {
	b.log.Info("[JOB] Received job", map[string]any{
		"job_id":   job.ID,
		"test_id":  job.TestID,
		"executor": job.Executor,
	})

	// Verify HMAC signature
	if !b.verifyJobSignature(job) {
		b.log.Error("[JOB] Signature verification FAILED - refusing to execute", map[string]any{
			"job_id": job.ID,
		})
		return
	}

	// Download payload if needed
	command := job.Command
	if job.DownloadURL != "" {
		payloadPath, err := b.exec.DownloadPayload(job.DownloadURL, job.TestID)
		if err != nil {
			b.log.Error("[JOB] Payload download failed", map[string]any{
				"job_id": job.ID,
				"url":    job.DownloadURL,
				"error":  err.Error(),
			})
			b.reportResult(job.ID, -1, "", err.Error(), 0)
			return
		}
		command = replaceArg(command, "{{payload}}", payloadPath)
	}

	// Resolve input args
	command = b.exec.ResolveInputArgs(command, job.InputArgs)

	// Execute
	timeout := time.Duration(job.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 300 * time.Second
	}

	start := time.Now()
	result, execErr := b.exec.Execute(job.Executor, command, timeout)
	durationMs := int(time.Since(start).Milliseconds())

	exitCode := 0
	stdout := ""
	stderr := ""

	if execErr != nil {
		b.log.Warn("[JOB] Execution error", map[string]any{
			"job_id": job.ID,
			"error":  execErr.Error(),
		})
		exitCode = -1
		stderr = execErr.Error()
	} else if result != nil {
		exitCode = result.ExitCode
		stdout = result.Stdout
		stderr = result.Stderr
	}

	// Write immutable execution log
	logger.ExecutionLog(logger.ExecLogPath(), map[string]any{
		"job_id":       job.ID,
		"test_id":      job.TestID,
		"executor":     job.Executor,
		"command_hash": sha256Hex(command),
		"exit_code":    exitCode,
		"duration_ms":  durationMs,
	})

	b.log.Info("[JOB] Completed", map[string]any{
		"job_id":      job.ID,
		"exit_code":   exitCode,
		"duration_ms": durationMs,
	})

	b.reportResult(job.ID, exitCode, stdout, stderr, durationMs)
}

func (b *Beacon) reportResult(jobID string, exitCode int, stdout, stderr string, durationMs int) {
	maxBytes := b.cfg.MaxOutputBytes
	if maxBytes <= 0 {
		maxBytes = 102400
	}
	if len(stdout) > maxBytes {
		stdout = stdout[:maxBytes]
	}
	if len(stderr) > maxBytes {
		stderr = stderr[:maxBytes]
	}

	payload := map[string]any{
		"paw":         b.cfg.PAW,
		"job_id":      jobID,
		"exit_code":   exitCode,
		"stdout":      stdout,
		"stderr":      stderr,
		"duration_ms": durationMs,
	}

	data, err := json.Marshal(payload)
	if err != nil {
		b.log.Error("[RESULT] Marshal failed", map[string]any{"error": err.Error()})
		return
	}

	url := fmt.Sprintf("%s/api/v2/agent/result", b.cfg.ServerURL)
	req, err := http.NewRequest("POST", url, bytes.NewReader(data))
	if err != nil {
		b.log.Error("[RESULT] Request creation failed", map[string]any{"error": err.Error()})
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+b.cfg.AgentToken)

	resp, err := b.client.Do(req)
	if err != nil {
		b.log.Error("[RESULT] Send failed", map[string]any{"error": err.Error()})
		return
	}
	defer resp.Body.Close()

	b.log.Debug("[RESULT] Sent", map[string]any{"job_id": jobID, "status": resp.StatusCode})
}

func (b *Beacon) sendHeartbeat() {
	payload := map[string]any{
		"paw":    b.cfg.PAW,
		"status": "idle",
	}
	data, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/api/v2/agent/heartbeat", b.cfg.ServerURL)
	req, err := http.NewRequest("POST", url, bytes.NewReader(data))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+b.cfg.AgentToken)
	resp, err := b.client.Do(req)
	if err != nil {
		b.log.Debug("[HEARTBEAT] Failed", map[string]any{"error": err.Error()})
		return
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	b.log.Debug("[HEARTBEAT] Sent", map[string]any{"paw": b.cfg.PAW})
}

func (b *Beacon) verifyJobSignature(job *Job) bool {
	if job.Signature == "" {
		return true // No signature - allow (dev mode)
	}
	// The server signs: job.id + ":" + job.command + ":" + job.executor
	// We verify using HMAC-SHA256 with the agent token as the key
	payload := fmt.Sprintf("%s:%s:%s", job.ID, job.Command, job.Executor)
	mac := hmac.New(sha256.New, []byte(b.cfg.AgentToken))
	mac.Write([]byte(payload))
	expected := hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(expected), []byte(job.Signature))
}

func sha256Hex(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

func replaceArg(command, placeholder, value string) string {
	result := command
	for i := 0; i < len(result); i++ {
		idx := indexOf(result, placeholder)
		if idx == -1 {
			break
		}
		result = result[:idx] + value + result[idx+len(placeholder):]
	}
	return result
}

func indexOf(s, substr string) int {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}
