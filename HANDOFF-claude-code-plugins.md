# Handoff: Install 5 Claude Code plugins from an Instagram reel

## Goal

Find, vet and install five Claude Code plugins recommended in an Instagram reel, on the user's own machine (Windows, user `Bem`; this repo is at `C:\Users\Bem\Desktop\video-editor`). Install into the user's Claude Code setup, not only this project, unless a plugin is meant to be project-scoped.

## Where this came from

A 57-second reel (instagram.com/reel/Dbn6ElTvw_W), transcribed in an earlier session. **None of the claims below were verified** — that session had no web access. The only hard evidence of a real source is a GitHub star-history chart shown on screen for `thedotmack/claude-mem`.

| # | Name as spoken | Claimed function | Known source |
|---|---|---|---|
| 1 | OmniRoute | Router to 200+ free AI API providers; auto-switches model when Claude usage limits run out ("1.6B free tokens/month") | Unknown — find it |
| 2 | Claude Mem | Persistent memory across sessions | `github.com/thedotmack/claude-mem` (shown in video) |
| 3 | Headroom | Proxy/compressor between you and the model; trims context to save tokens | Unknown — find it |
| 4 | Claude Code Setup | Described as an *official Anthropic* plugin; scans the codebase and recommends hooks, skills, subagents, MCP servers | Unverified — check Anthropic's official plugin marketplace |
| 5 | Task Observer | Watches how you work and improves your other skills in the background | Unknown — find it |

Names came from speech-to-text, so spellings may differ slightly (e.g. "Omni Route", "claude-mem", "headroom").

## Steps

1. **Locate each plugin.** Search GitHub and the Claude Code plugin marketplaces for the exact project. Prefer the canonical repo (most stars, matching description, active maintainer) over forks or lookalikes. Record the URL and publisher for each.
2. **Vet before installing.** For each plugin, read its README and skim the source, specifically:
   - Hooks (anything run on tool calls, session start, prompt submit) and what commands they execute.
   - Network calls: where prompts, code or files get sent.
   - Install scripts (`postinstall`, shell scripts, `curl | sh`).
   - Credentials or API keys it asks for, and where it stores them.
   - Background processes or daemons it starts.
3. **Report findings to the user before installing anything** — one short line per plugin: repo URL, publisher, what it actually does, and any concerns. Wait for their go-ahead per plugin.
4. **Install** using the plugin's documented method — normally in Claude Code:
   ```
   /plugin marketplace add <owner>/<repo>
   /plugin install <plugin-name>@<marketplace>
   ```
   Some (OmniRoute, Headroom) may instead be a proxy/server or an MCP server with its own setup (npm/pip package, env vars such as `ANTHROPIC_BASE_URL`). Follow their README; don't improvise.
5. **Verify** each one loads: run `/plugin` to list installed plugins, restart Claude Code if required, and do a quick smoke test of its main feature.
6. **Summarize** for the user: what's installed, where, any config/env vars added, and how to uninstall each.

## Required checks — stop and ask the user if any apply

- **OmniRoute / Headroom route your traffic.** They likely sit between Claude Code and the API (e.g. by overriding `ANTHROPIC_BASE_URL`). That means prompts and code go through a third party, and OmniRoute may answer with non-Claude models. Spell this out and get explicit consent first. Don't install them on a machine with confidential work unless the user approves it.
- **"Official Anthropic" claim.** Only treat Claude Code Setup as official if it's published by Anthropic (an `anthropics` GitHub org or Anthropic's official marketplace). If you can't confirm it, say so.
- **Can't find a plugin, or there are several candidates** → don't guess. Report what you found and let the user pick.
- **Anything that asks for API keys, account logins, or broad permissions** (e.g. bypassing permission prompts) → ask first.
- Never disable security settings or permission prompts to make a plugin work.

## Done when

Every plugin the user approved is installed and shows up in `/plugin`, its main feature works, and the user has a summary listing each plugin's source, what it changed, and how to remove it. Plugins that were skipped or not found are listed with the reason.
