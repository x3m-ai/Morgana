// Linux systemd service manager.
//go:build !windows

package service

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/x3m-ai/morgana-agent/internal/beacon"
	"github.com/x3m-ai/morgana-agent/internal/config"
	"github.com/x3m-ai/morgana-agent/internal/logger"
)

// New returns the Linux systemd service manager.
func New(name, description string) Manager {
	return newLinuxManager(name, description)
}


const systemdUnitTemplate = `[Unit]
Description=Morgana Red Team Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/morgana-agent run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=morgana-agent
User=root

[Install]
WantedBy=multi-user.target
`

const systemdUnitPath = "/etc/systemd/system/morgana-agent.service"
const agentBinaryPath = "/usr/local/bin/morgana-agent"

type linuxManager struct {
	name string
	desc string
	log  *logger.Logger
}

func newLinuxManager(name, description string) Manager {
	return &linuxManager{name: name, desc: description, log: logger.New("morgana.service.linux")}
}

func (m *linuxManager) Install(serverURL, deployToken string, interval int) (*config.Config, error) {
	hostname, _ := os.Hostname()
	arch := runtime.GOARCH
	osVersion := "Linux"
	if out, err := os.ReadFile("/etc/os-release"); err == nil {
		for _, line := range strings.Split(string(out), "\n") {
			if strings.HasPrefix(line, "PRETTY_NAME=") {
				osVersion = strings.Trim(strings.TrimPrefix(line, "PRETTY_NAME="), `"`)
				break
			}
		}
	}

	// Register with server
	m.log.Info("[INSTALL] Registering with Morgana server", map[string]any{"server": serverURL})
	cfg, err := RegisterWithServer(serverURL, deployToken, hostname, "linux", arch, osVersion)
	if err != nil {
		return nil, fmt.Errorf("server registration failed: %w", err)
	}
	cfg.BeaconInterval = interval

	// Create directories
	for _, dir := range []string{"/etc/morgana", "/var/lib/morgana/work", "/var/log/morgana"} {
		os.MkdirAll(dir, 0755)
	}
	cfg.WorkDir = "/var/lib/morgana/work"

	// Copy binary
	if err := copySelf(agentBinaryPath); err != nil {
		m.log.Warn("[INSTALL] Could not copy binary", map[string]any{"error": err.Error()})
	}
	os.Chmod(agentBinaryPath, 0755)

	// Save config
	if err := config.Save(cfg); err != nil {
		return nil, fmt.Errorf("save config: %w", err)
	}
	if err := config.SaveAgentToken(cfg.AgentToken); err != nil {
		return nil, fmt.Errorf("save agent token: %w", err)
	}

	m.log.Info("[INSTALL] Enrolled", map[string]any{"paw": cfg.PAW})

	// Write systemd unit
	if err := os.WriteFile(systemdUnitPath, []byte(systemdUnitTemplate), 0644); err != nil {
		return nil, fmt.Errorf("write systemd unit: %w", err)
	}

	// Enable and start
	for _, cmd := range [][]string{
		{"systemctl", "daemon-reload"},
		{"systemctl", "enable", "morgana-agent"},
		{"systemctl", "start", "morgana-agent"},
	} {
		if out, err := exec.Command(cmd[0], cmd[1:]...).CombinedOutput(); err != nil {
			m.log.Warn("[INSTALL] systemctl command failed", map[string]any{
				"cmd":   strings.Join(cmd, " "),
				"error": err.Error(),
				"out":   string(out),
			})
		}
	}

	return cfg, nil
}

func (m *linuxManager) Uninstall(purge bool) error {
	for _, cmd := range [][]string{
		{"systemctl", "stop", "morgana-agent"},
		{"systemctl", "disable", "morgana-agent"},
	} {
		exec.Command(cmd[0], cmd[1:]...).Run()
	}
	os.Remove(systemdUnitPath)
	exec.Command("systemctl", "daemon-reload").Run()
	os.Remove(agentBinaryPath)

	if purge {
		for _, dir := range []string{"/etc/morgana", "/var/lib/morgana", "/var/log/morgana"} {
			os.RemoveAll(dir)
		}
	}
	return nil
}

func (m *linuxManager) RunForeground(cfg *config.Config) error {
	logger.InitFile(logger.AgentLogPath())
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	b := beacon.New(cfg)
	return b.Run(ctx)
}

func (m *linuxManager) Status() (string, error) {
	out, err := exec.Command("systemctl", "status", "morgana-agent", "--no-pager", "-l").CombinedOutput()
	if err != nil {
		return string(out), nil
	}
	return string(out), nil
}

func copySelf(dest string) error {
	src, err := os.Executable()
	if err != nil {
		return err
	}
	srcAbs, _ := filepath.EvalSymlinks(src)
	destAbs, _ := filepath.EvalSymlinks(dest)
	if srcAbs == destAbs {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
