// Morgana Agent - Main entry point
// Usage:
//   morgana-agent install   --server <url> --token <deploy_token> [--interval 30]
//   morgana-agent uninstall [--purge]
//   morgana-agent run                  (foreground / debug mode)
//   morgana-agent status
//   morgana-agent version

package main

import (
	"flag"
	"fmt"
	"os"
	"runtime"

	"github.com/x3m-ai/morgana-agent/internal/config"
	"github.com/x3m-ai/morgana-agent/internal/logger"
	"github.com/x3m-ai/morgana-agent/internal/service"
)

const (
	AgentVersion = "0.1.0"
	ServiceName  = "MorganaAgent"
	ServiceDesc  = "Morgana Red Team Agent - X3M.AI Purple Team Platform"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	log := logger.New("morgana.main")

	switch os.Args[1] {
	case "install":
		handleInstall(log)
	case "uninstall":
		handleUninstall(log)
	case "run":
		handleRun(log)
	case "status":
		handleStatus(log)
	case "version":
		fmt.Printf("Morgana Agent v%s (%s/%s)\n", AgentVersion, runtime.GOOS, runtime.GOARCH)
	default:
		printUsage()
		os.Exit(1)
	}
}

func handleInstall(log *logger.Logger) {
	fs := flag.NewFlagSet("install", flag.ExitOnError)
	serverURL := fs.String("server", "", "Morgana server URL (required)")
	token := fs.String("token", "", "Deploy token from Morgana server (required)")
	interval := fs.Int("interval", 30, "Beacon interval in seconds (default: 30)")
	_ = fs.Parse(os.Args[2:])

	if *serverURL == "" || *token == "" {
		fmt.Fprintln(os.Stderr, "ERROR: --server and --token are required for install")
		os.Exit(1)
	}

	log.Info("[INSTALL] Installing Morgana Agent", map[string]any{
		"server":   *serverURL,
		"interval": *interval,
		"platform": runtime.GOOS,
		"version":  AgentVersion,
	})

	svc := service.New(ServiceName, ServiceDesc)

	cfg, err := svc.Install(*serverURL, *token, *interval)
	if err != nil {
		log.Error("[INSTALL] Failed", map[string]any{"error": err.Error()})
		fmt.Fprintf(os.Stderr, "ERROR: Install failed: %v\n", err)
		os.Exit(1)
	}

	log.Info("[INSTALL] Agent installed", map[string]any{
		"paw": cfg.PAW,
	})
	fmt.Printf("SUCCESS: Morgana Agent installed.\n")
	fmt.Printf("  PAW:      %s\n", cfg.PAW)
	fmt.Printf("  Server:   %s\n", cfg.ServerURL)
	fmt.Printf("  Interval: %ds\n", cfg.BeaconInterval)
	fmt.Printf("  Work dir: %s\n", cfg.WorkDir)
	fmt.Printf("\nIf the service did not start automatically run:\n  sc start MorganaAgent\n")
}

func handleUninstall(log *logger.Logger) {
	fs := flag.NewFlagSet("uninstall", flag.ExitOnError)
	purge := fs.Bool("purge", false, "Remove all Morgana data directories")
	_ = fs.Parse(os.Args[2:])

	log.Info("[UNINSTALL] Uninstalling Morgana Agent", nil)

	svc := service.New(ServiceName, ServiceDesc)
	if err := svc.Uninstall(*purge); err != nil {
		log.Error("[UNINSTALL] Failed", map[string]any{"error": err.Error()})
		fmt.Fprintf(os.Stderr, "ERROR: Uninstall failed: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("SUCCESS: Morgana Agent uninstalled.")
	if *purge {
		fmt.Println("All Morgana data directories removed.")
	}
}

func handleRun(log *logger.Logger) {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	serverURL := fs.String("server", "", "Morgana server URL (skips reading from config file)")
	token := fs.String("token", "", "Deploy token (required when --server is set)")
	interval := fs.Int("interval", 30, "Beacon interval in seconds")
	fs.Parse(os.Args[2:])

	var cfg *config.Config

	if *serverURL != "" {
		// Standalone mode: register directly without installing the NT service
		if *token == "" {
			fmt.Fprintln(os.Stderr, "ERROR: --token is required when --server is set")
			os.Exit(1)
		}

		hostname, _ := os.Hostname()
		var err error
		cfg, err = service.RegisterWithServer(*serverURL, *token, hostname, runtime.GOOS, runtime.GOARCH, "run-mode", )
		if err != nil {
			log.Error("[RUN] Registration failed", map[string]any{"error": err.Error()})
			fmt.Fprintf(os.Stderr, "ERROR: Registration failed: %v\n", err)
			os.Exit(1)
		}
		cfg.BeaconInterval = *interval
		log.Info("[RUN] Registered in standalone mode", map[string]any{
			"paw":      cfg.PAW,
			"server":   cfg.ServerURL,
			"interval": cfg.BeaconInterval,
		})
	} else {
		// Normal mode: load config written by 'install'
		var err error
		cfg, err = config.Load()
		if err != nil {
			log.Error("[RUN] Cannot load config - use 'install' or pass --server/--token", map[string]any{"error": err.Error()})
			fmt.Fprintf(os.Stderr, "ERROR: %v\nTip: morgana-agent run --server <url> --token <token>\n", err)
			os.Exit(1)
		}
	}

	log.Info("[RUN] Starting Morgana Agent (foreground)", map[string]any{
		"paw":      cfg.PAW,
		"server":   cfg.ServerURL,
		"interval": cfg.BeaconInterval,
		"version":  AgentVersion,
	})

	svc := service.New(ServiceName, ServiceDesc)
	if err := svc.RunForeground(cfg); err != nil {
		log.Error("[RUN] Agent stopped with error", map[string]any{"error": err.Error()})
		os.Exit(1)
	}
}

func handleStatus(log *logger.Logger) {
	svc := service.New(ServiceName, ServiceDesc)
	status, err := svc.Status()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Status error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(status)
}

func printUsage() {
	fmt.Printf(`Morgana Agent v%s - X3M.AI Purple Team Platform

USAGE:
  morgana-agent <command> [options]

COMMANDS:
  install    Install as OS service (requires Administrator/root)
    --server <url>    Morgana server URL (required)
    --token  <token>  Deploy token from Morgana server (required)
    --interval <n>    Beacon interval seconds (default: 30)

  uninstall  Remove the OS service
    --purge           Also remove all data directories

  run        Run in foreground (debug mode, no service required)
    --server <url>    Connect directly without installing service (optional)
    --token  <token>  Deploy token, required if --server is set
    --interval <n>    Beacon interval seconds (default: 30)

  status     Show service status

  version    Print version information

EXAMPLES:
  morgana-agent install --server https://192.168.1.10:8888 --token DEPLOY_TOKEN_HERE
  morgana-agent run --server http://localhost:8888 --token MORGANA_ADMIN_KEY
  morgana-agent uninstall --purge
  morgana-agent status
`, AgentVersion)
}
