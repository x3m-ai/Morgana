# MILESTONE - open and change implemented - happy

**Date:** 2026-04-04
**Base commit:** b85dfe2
**Branch:** master

## Summary

Open and Change buttons fully implemented on chain and campaign flow editor nodes.

## Changes

### ui/app.js
- `_renderScriptNodeHTML`: "Open" now calls `openChainNodeScript()` (shows script detail modal); "Change" calls the existing `replaceChainScript()` picker
- `_renderCampChainNodeHTML`: "Open" now calls `openCampNodeChain()` (shows chain detail modal); "Change" calls the existing `replaceCampChain()` picker
- New `_findNodeInTree(nodes, nodeId)`: recursive walker for chain node tree (handles if/else branches)
- New `openChainNodeScript(nodeId)`: looks up node in chain tree, ensures allScripts cache loaded, opens existing scriptModal in read/edit mode
- New `_findCampNodeInTree(nodes, nodeId)`: recursive walker for campaign node tree (handles parallel branches)
- New `openCampNodeChain(nodeId)`: looks up node in campaign tree, fetches chain from _allChains cache or API, populates and shows chainDetailModal
- New `closeChainDetailModal()`: hides chainDetailModal
- Cache-busting suffix bumped to `?v=3`

### ui/index.html
- New `chainDetailModal`: read-only modal showing chain name, description, and ordered script table (tactic, tcode, script name)
- Cache-busting suffix bumped to `?v=3`
