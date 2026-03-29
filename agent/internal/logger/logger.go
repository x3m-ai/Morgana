// Package logger provides structured JSON logging for the Morgana Agent.
package logger

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"gopkg.in/lumberjack.v2"
)

type Level int

const (
	DEBUG Level = iota
	INFO
	WARN
	ERROR
)

func (l Level) String() string {
	return [...]string{"DEBUG", "INFO", "WARN", "ERROR"}[l]
}

// globalWriter is the shared destination for all loggers.
// All Logger instances write here, so InitFile() affects every logger
// even those created before the file was opened.
var (
	globalWriter io.Writer = os.Stdout
	globalLevel            = parseEnvLevel()
	globalMu     sync.RWMutex
)

// parseEnvLevel reads MORGANA_LOG_LEVEL (DEBUG/INFO/WARN/ERROR), defaults INFO.
func parseEnvLevel() Level {
	switch strings.ToUpper(os.Getenv("MORGANA_LOG_LEVEL")) {
	case "DEBUG":
		return DEBUG
	case "WARN", "WARNING":
		return WARN
	case "ERROR":
		return ERROR
	default:
		return INFO
	}
}

// InitFile sets up a rotating log file. Safe to call at any point; all
// existing Logger instances immediately start writing to the file.
// Rotation: 10 MB per file, 5 backups kept, 30-day retention, compressed.
func InitFile(path string) {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		fmt.Fprintf(os.Stderr, "[logger] could not create log dir: %v\n", err)
		return
	}
	rotator := &lumberjack.Logger{
		Filename:   path,
		MaxSize:    10, // MB
		MaxBackups: 5,
		MaxAge:     30, // days
		Compress:   true,
		LocalTime:  false,
	}
	globalMu.Lock()
	globalWriter = io.MultiWriter(os.Stdout, rotator)
	globalMu.Unlock()
}

type Logger struct {
	name string
}

// New creates a new Logger with the given name.
// It always uses the current globalWriter, so InitFile() applies retroactively.
func New(name string) *Logger {
	return &Logger{name: name}
}

func (l *Logger) log(level Level, msg string, fields map[string]any) {
	globalMu.RLock()
	lvl := globalLevel
	w := globalWriter
	globalMu.RUnlock()

	if level < lvl {
		return
	}

	entry := map[string]any{
		"ts":    time.Now().UTC().Format(time.RFC3339),
		"level": level.String(),
		"name":  l.name,
		"msg":   msg,
	}
	for k, v := range fields {
		entry[k] = v
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return
	}
	fmt.Fprintln(w, string(data))
}

func (l *Logger) Debug(msg string, fields map[string]any) { l.log(DEBUG, msg, fields) }
func (l *Logger) Info(msg string, fields map[string]any)  { l.log(INFO, msg, fields) }
func (l *Logger) Warn(msg string, fields map[string]any)  { l.log(WARN, msg, fields) }
func (l *Logger) Error(msg string, fields map[string]any) { l.log(ERROR, msg, fields) }

// ExecutionLog writes an immutable append-only execution audit entry.
func ExecutionLog(path string, entry map[string]any) {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
	if err != nil {
		return
	}
	defer f.Close()

	entry["ts"] = time.Now().UTC().Format(time.RFC3339)
	data, err := json.Marshal(entry)
	if err != nil {
		return
	}
	fmt.Fprintln(f, string(data))
}

// ExecLogPath returns the platform-appropriate execution log path.
func ExecLogPath() string {
	if runtime.GOOS == "windows" {
		return strings.Join([]string{os.Getenv("ProgramData"), "Morgana", "logs", "execution.log"}, string(filepath.Separator))
	}
	return "/var/log/morgana/execution.log"
}

// AgentLogPath returns the platform-appropriate agent log path.
func AgentLogPath() string {
	if runtime.GOOS == "windows" {
		return strings.Join([]string{os.Getenv("ProgramData"), "Morgana", "logs", "agent.log"}, string(filepath.Separator))
	}
	return "/var/log/morgana/agent.log"
}
