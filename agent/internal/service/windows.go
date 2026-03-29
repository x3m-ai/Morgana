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

	// Copy binary to install dir; fall back to current exe path if copy fails
	exePath := filepath.Join(installDir, "morgana-agent.exe")
	if err := copySelf(exePath); err != nil {
		m.log.Warn("[INSTALL] Could not copy binary to install dir, using current exe path", map[string]any{"error": err.Error()})
		if self, selfErr := os.Executable(); selfErr == nil {
			exePath = self
		}
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

	// Start the service — best effort, may require a second elevated call on some systems
	if err := m.startNTService(); err != nil {
		m.log.Warn("[INSTALL] NT Service installed but could not auto-start (start it manually with: sc start MorganaAgent)", map[string]any{"error": err.Error()})
	} else {
		m.log.Info("[INSTALL] NT Service started", nil)
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

	s, err := scm.CreateService(m.name, exePath, svcConfig, "run")
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

	// Detect whether we are invoked by the Windows SCM (service mode) or interactively.
	isService, err := svc.IsWindowsService()
	if err != nil {
		return fmt.Errorf("svc.IsWindowsService: %w", err)
	}

	if isService {
		// Hand control to the SCM — Execute() will be called by the runtime.
		return svc.Run(m.name, &agentService{cfg: cfg, log: m.log})
	}

	// Interactive / standalone mode (e.g. run from a terminal).
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	b := beacon.New(cfg)
	return b.Run(ctx)
}

// agentService implements golang.org/x/sys/windows/svc.Handler.
type agentService struct {
	cfg *config.Config
	log *logger.Logger
}

// Execute is the entry point called by the Windows SCM.
func (a *agentService) Execute(args []string, r <-chan svc.ChangeRequest, s chan<- svc.Status) (svcSpecificEC bool, exitCode uint32) {
	// Signal to SCM that we are running and accept Stop + Shutdown.
	s <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan error, 1)
	go func() {
		b := beacon.New(a.cfg)
		done <- b.Run(ctx)
	}()

	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Stop, svc.Shutdown:
				a.log.Info("[RUN] Stop requested by SCM", nil)
				s <- svc.Status{State: svc.StopPending}
				cancel()
				<-done
				return false, 0
			case svc.Interrogate:
				s <- c.CurrentStatus
			}
		case err := <-done:
			if err != nil {
				a.log.Error("[RUN] Beacon exited with error", map[string]any{"error": err.Error()})
			}
			return false, 0
		}
	}
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
