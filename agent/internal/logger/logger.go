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

type Logger struct {
	name  string
	level Level
	out   io.Writer
	mu    sync.Mutex
}

var (
	defaultLevel = INFO
	logFile      io.Writer
	once         sync.Once
)

// InitFile opens the log file for writing.
func InitFile(path string) {
	once.Do(func() {
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return
		}
		f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			return
		}
		logFile = f
	})
}

// New creates a new Logger with the given name.
func New(name string) *Logger {
	writers := []io.Writer{os.Stdout}
	if logFile != nil {
		writers = append(writers, logFile)
	}
	return &Logger{
		name:  name,
		level: defaultLevel,
		out:   io.MultiWriter(writers...),
	}
}

func (l *Logger) log(level Level, msg string, fields map[string]any) {
	if level < l.level {
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

	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Fprintln(l.out, string(data))
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
