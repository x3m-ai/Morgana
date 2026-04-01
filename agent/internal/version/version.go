// Package version is the single source of truth for the Morgana Agent version.
// All packages that need the version string import this package.
package version

const (
	// Agent is the current agent binary version. Bump on every release.
	Agent = "0.2.0"
)
