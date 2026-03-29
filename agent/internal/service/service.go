// Package service handles OS service installation, management, and lifecycle.
package service

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"

	"crypto/tls"

	"github.com/x3m-ai/morgana-agent/internal/config"
)

// Manager is the interface for OS-specific service management.
type Manager interface {
	Install(serverURL, deployToken string, interval int) (*config.Config, error)
	Uninstall(purge bool) error
	RunForeground(cfg *config.Config) error
	Status() (string, error)
}

// RegisterWithServer calls the Morgana server to enroll this agent.
// Returns the config populated with paw and agent_token from the server.
func RegisterWithServer(serverURL, deployToken, hostname, platform, arch, osVersion string) (*config.Config, error) {
	payload := map[string]any{
		"deploy_token": deployToken,
		"hostname":     hostname,
		"platform":     platform,
		"architecture": arch,
		"os_version":   osVersion,
		"agent_version": "0.1.0",
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	// Accept self-signed certs for enrollment (lab use)
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client := &http.Client{Transport: transport}

	url := fmt.Sprintf("%s/api/v2/agent/register", serverURL)
	req, err := http.NewRequest("POST", url, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("cannot reach Morgana server at %s: %w", serverURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server registration failed with status %d", resp.StatusCode)
	}

	var regResp struct {
		PAW                   string `json:"paw"`
		AgentToken            string `json:"agent_token"`
		ServerCertFingerprint string `json:"server_cert_fingerprint"`
		BeaconInterval        int    `json:"beacon_interval"`
		WorkDir               string `json:"work_dir"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&regResp); err != nil {
		return nil, fmt.Errorf("decode registration response: %w", err)
	}

	cfg := &config.Config{
		ServerURL:             serverURL,
		ServerCertFingerprint: regResp.ServerCertFingerprint,
		PAW:                   regResp.PAW,
		BeaconInterval:        regResp.BeaconInterval,
		MaxExecutionTimeout:   300,
		MaxOutputBytes:        102400,
		WorkDir:               regResp.WorkDir,
		LogLevel:              "info",
		AgentToken:            regResp.AgentToken,
	}

	return cfg, nil
}
