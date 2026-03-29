// Windows NT Service manager.
//go:build windows

package service

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"github.com/x3m-ai/morgana-agent/internal/beacon"
	"github.com/x3m-ai/morgana-agent/internal/config"
	"github.com/x3m-ai/morgana-agent/internal/logger"
)

// New returns the Windows NT service manager.
func New(name, description string) Manager {
	return newWindowsManager(name, description)
}


type windowsManager struct {
	name string
	desc string
	log  *logger.Logger
}

func newWindowsManager(name, description string) Manager {
	return &windowsManager{name: name, desc: description, log: logger.New("morgana.service.windows")}
}

func (m *windowsManager) Install(serverURL, deployToken string, interval int) (*config.Config, error) {
	hostname, _ := os.Hostname()
	arch := runtime.GOARCH

	osVersion := "Windows"
	if out, err := exec.Command("cmd", "/C", "ver").Output(); err == nil {
		osVersion = string(out)
	}

	// Register with server
	m.log.Info("[INSTALL] Registering with Morgana server", map[string]any{"server": serverURL})
	cfg, err := RegisterWithServer(serverURL, deployToken, hostname, "windows", arch, osVersion)
	if err != nil {
		return nil, fmt.Errorf("server registration failed: %w", err)
	}
	cfg.BeaconInterval = interval

	// Create directories
	installDir := filepath.Join(os.Getenv("ProgramData"), "Morgana", "agent")
	workDir := filepath.Join(os.Getenv("ProgramData"), "Morgana", "work")
	logDir := filepath.Join(os.Getenv("ProgramData"), "Morgana", "logs")
	for _, dir := range []string{installDir, workDir, logDir} {
		os.MkdirAll(dir, 0755)
	}
	cfg.WorkDir = workDir

	// Copy binary to install dir
	exePath := filepath.Join(installDir, "morgana-agent.exe")
	if err := copySelf(exePath); err != nil {
		m.log.Warn("[INSTALL] Could not copy binary (already installed?)", map[string]any{"error": err.Error()})
	}

	// Save config
	if err := config.Save(cfg); err != nil {
		return nil, fmt.Errorf("save config: %w", err)
	}

	// Save agent token securely
	if err := config.SaveAgentToken(cfg.AgentToken); err != nil {
		return nil, fmt.Errorf("save agent token: %w", err)
	}

	m.log.Info("[INSTALL] Enrolled", map[string]any{"paw": cfg.PAW})

	// Install as NT Service
	if err := m.installNTService(exePath); err != nil {
		return nil, fmt.Errorf("NT Service install: %w", err)
	}

	// Start the service
	if err := m.startNTService(); err != nil {
		return nil, fmt.Errorf("NT Service start: %w", err)
	}

	return cfg, nil
}

func (m *windowsManager) installNTService(exePath string) error {
	scm, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("open SCM: %w", err)
	}
	defer scm.Disconnect()

	// Remove existing service if present
	existing, err := scm.OpenService(m.name)
	if err == nil {
		existing.Control(svc.Stop)
		time.Sleep(2 * time.Second)
		existing.Delete()
		existing.Close()
	}

	svcConfig := mgr.Config{
		DisplayName:      m.desc,
		Description:      m.desc,
		StartType:        mgr.StartAutomatic,
		ServiceStartName: "LocalSystem",
	}

	s, err := scm.CreateService(m.name, exePath+" run", svcConfig)
	if err != nil {
		return fmt.Errorf("create service: %w", err)
	}
	defer s.Close()

	// Set failure actions: restart on failure
	s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 5 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 10 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 30 * time.Second},
	}, 0)

	m.log.Info("[INSTALL] NT Service created", map[string]any{"name": m.name})
	return nil
}

func (m *windowsManager) startNTService() error {
	scm, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer scm.Disconnect()
	s, err := scm.OpenService(m.name)
	if err != nil {
		return err
	}
	defer s.Close()
	return s.Start()
}

func (m *windowsManager) Uninstall(purge bool) error {
	scm, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("open SCM: %w", err)
	}
	defer scm.Disconnect()

	s, err := scm.OpenService(m.name)
	if err != nil {
		return fmt.Errorf("service not found: %w", err)
	}
	defer s.Close()

	s.Control(svc.Stop)
	time.Sleep(3 * time.Second)
	s.Delete()
	m.log.Info("[UNINSTALL] NT Service removed", nil)

	if purge {
		base := filepath.Join(os.Getenv("ProgramData"), "Morgana")
		os.RemoveAll(base)
		m.log.Info("[UNINSTALL] Data directories removed", map[string]any{"path": base})
	}
	return nil
}

func (m *windowsManager) RunForeground(cfg *config.Config) error {
	logger.InitFile(logger.AgentLogPath())
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	b := beacon.New(cfg)
	return b.Run(ctx)
}

func (m *windowsManager) Status() (string, error) {
	scm, err := mgr.Connect()
	if err != nil {
		return "", err
	}
	defer scm.Disconnect()
	s, err := scm.OpenService(m.name)
	if err != nil {
		return "NOT INSTALLED", nil
	}
	defer s.Close()
	status, err := s.Query()
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("Service: %s | State: %v", m.name, status.State), nil
}

func copySelf(dest string) error {
	src, err := os.Executable()
	if err != nil {
		return err
	}
	if src == dest {
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
