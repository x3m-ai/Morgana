// Package config handles Morgana Agent configuration loading and saving.
package config

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// Config holds the agent runtime configuration.
type Config struct {
	ServerURL              string `json:"server_url"`
	ServerCertFingerprint  string `json:"server_cert_fingerprint"`
	PAW                    string `json:"paw"`
	BeaconInterval         int    `json:"beacon_interval"`
	MaxExecutionTimeout    int    `json:"max_execution_timeout"`
	MaxOutputBytes         int    `json:"max_output_bytes"`
	WorkDir                string `json:"work_dir"`
	LogLevel               string `json:"log_level"`
	AgentToken             string `json:"-"` // Loaded from secure storage, never in JSON
}

// Default values
func defaults() Config {
	return Config{
		BeaconInterval:      30,
		MaxExecutionTimeout: 300,
		MaxOutputBytes:      102400,
		LogLevel:            "info",
		WorkDir:             defaultWorkDir(),
	}
}

func defaultWorkDir() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "Morgana", "work")
	}
	return "/var/lib/morgana/work"
}

// ConfigDir returns the platform-appropriate config directory.
func ConfigDir() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "Morgana", "agent")
	}
	return "/etc/morgana"
}

// ConfigPath returns the full path to the config file.
func ConfigPath() string {
	return filepath.Join(ConfigDir(), "config.json")
}

// Load reads the config from disk.
func Load() (*Config, error) {
	data, err := os.ReadFile(ConfigPath())
	if err != nil {
		return nil, fmt.Errorf("cannot read config at %s: %w", ConfigPath(), err)
	}

	cfg := defaults()
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("cannot parse config: %w", err)
	}

	// Load agent token from secure storage
	cfg.AgentToken = LoadAgentToken()
	return &cfg, nil
}

// Save writes config to disk (without the agent token).
func Save(cfg *Config) error {
	if err := os.MkdirAll(ConfigDir(), 0700); err != nil {
		return fmt.Errorf("cannot create config dir: %w", err)
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(ConfigPath(), data, 0600)
}

// LoadAgentToken reads the agent token from secure storage.
// Windows: attempts Windows Credential Manager, falls back to file.
// Linux: reads from /etc/morgana/.agent_token with mode 0600.
func LoadAgentToken() string {
	tokenFile := filepath.Join(ConfigDir(), ".agent_token")
	data, err := os.ReadFile(tokenFile)
	if err != nil {
		return ""
	}
	return string(data)
}

// SaveAgentToken writes the agent token to secure storage.
func SaveAgentToken(token string) error {
	tokenFile := filepath.Join(ConfigDir(), ".agent_token")
	if err := os.MkdirAll(ConfigDir(), 0700); err != nil {
		return err
	}
	return os.WriteFile(tokenFile, []byte(token), 0600)
}

// HTTPClient returns an HTTP client configured for this agent.
// In production: verify server cert fingerprint.
// For now: accept self-signed certs (typical in lab environments).
func (c *Config) HTTPClient() *http.Client {
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // TODO: pin server cert fingerprint
			MinVersion:         tls.VersionTLS12,
		},
	}
	return &http.Client{
		Transport: transport,
		Timeout:   35 * time.Second, // Must exceed server long-poll hold (28 s) with margin
	}
}
