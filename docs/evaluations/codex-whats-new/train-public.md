# Codex CLI release digest
## Environment
platform: linux
installed CLI: 0.160.1
Codex home: /example/.codex
project: /example/project
profile: subscription
project trust: trusted
terminal: kitty (via KITTY_PID)
TERM: xterm-kitty; multiplexer: none
setting approval_policy: on-request
setting sandbox_mode: workspace-write
setting model: gpt-5.6-terra
setting model_reasoning_effort: high
setting model_provider: openai
feature instant_interrupt: False
feature multi_agent: True
hooks: none found
mcp: reference
plugins: reference-plugin
skills: reference-skill
sources: /example/.codex/config.toml
hooks disabled in files: False
statusline: True
notifications: False
vim: False
keymap: False
otel: False
rules: True
sessions: True
git: True
environment variables (names only): none
File-based inventory, not the running session's effective configuration. CLI overrides, cloud defaults, enforced requirements, plugin-bundled content, and hook trust are not resolved. Unset features retain unknown runtime defaults.

Window: 0.159.0 through 0.159.3 (4 releases)
Baseline: 0.158.0
Signals watched: mcp, plugins, skills, permissions, subagents, statusline, sessions, git, provider, effort, compaction, new-setting, new-command, behavior-change, model, feature:multi_agent, term:kitty, new-feature
Withheld: 0 entries belonging to another platform
Unmatched: 78 entries matched no configuration signal
Not shown: 0 unmatched entries (--relevant-only)

## 0.159.3 (2026-09-30)
[new-feature] Eligible local sessions signed in with ChatGPT can now show optional reminders to complete account security setup. (#49744)
[-] Full Changelog: https://github.com/openai/codex/compare/rust-v0.159.2...rust-v0.159.3
[-] #49744 [0.159] Backport account security setup reminders for 0.159.3 @andrewgu-oai

## 0.159.2 (2026-09-29)
[permissions] Suppressed console windows flashing on Windows when Codex launches background processes and sandboxed commands. (#49385)
[-] Full Changelog: https://github.com/openai/codex/compare/rust-v0.159.1...rust-v0.159.2
[-] #49385 [0.159] Backport Windows console suppression for 0.159.2 @andrewgu-oai

## 0.159.1 (2026-09-29)
[provider,new-feature] Added GPT-6.1 Sol as the default model in the bundled catalog and Amazon Bedrock Mantle and Runtime catalogs. (#49323, #49342)
[-] Full Changelog: https://github.com/openai/codex/compare/rust-v0.159.0...rust-v0.159.1
[-] #49323 [0.159] Prepare 0.159.1 release backports @andrewgu-oai
[provider] #49342 [0.159] Backport GPT-6.1 Sol Bedrock catalogs @celia-oai

## 0.159.0 (2026-09-29)
[new-feature] Opt-in `instant_interrupt` lets new input steer Codex during model responses or long-running code-mode calls. (#48135, #48141)
[compaction,new-feature] New sessions get a compact welcome screen and consistent headers, with occasional tips during and after turns. (#48513, #48562, #48352)
[new-feature] The warnings viewer dismisses reviewed warnings when closed; press `k` to keep one for later. (#48205, #48206)
[new-feature] You can scroll the transcript while deciding whether to implement a plan. (#48805)
[new-feature] Native Mermaid rendering supports more flowchart edges, labels, and node groups. (#48814, #48895)
[new-feature] App-server clients can paginate thread history from a specific item. (#48151)
[mcp] Windows launches avoid stray console windows for MCP servers, code-mode hosts, and piped commands; restrictive launchers can fall back to embedded mode. (#48138, #48238, #48483, #48491)
[-] Copying transcript selections preserves Markdown tables, formatting, and significant whitespace. More terminals now copy automatically on selection. (#48548, #48549, #48469)
[-] Blank sessions retain drafts when switching tasks, and threads can be archived and listed before their first turn. (#48628, #48828, #48199)
[-] Local ChatGPT sign-in opens the browser reliably; onboarding also provides a shortcut to copy the login link. (#48502, #48544)
[-] Approved commands retain explicit filesystem denials, and `.aws` directories are protected by default under writable roots. (#48155, #48176)
[permissions] Fixed macOS TLS access in network-enabled sandboxes and remote environments that require proxy access. (#48565, #48198)
[behavior-change] Removed automatic follow-up prompt suggestions and the `tui.prompt_suggestions` setting. (#48621)
[plugins,skills,behavior-change] Removed the bundled `plugin-creator` skill. (#48604)
[-] Full Changelog: https://github.com/openai/codex/compare/rust-v0.158.0...rust-v0.159.0
[-] #48135 Add opt-in code-mode yielding on new user input @pakrym-oai
[-] #48138 Suppress console windows when spawning the code-mode host on Windows @zm-oai
[-] #48141 Preempt model responses when new user input arrives @pakrym-oai
[mcp] #48143 Preserve executor MCP credential boundaries across reconnects @rreichel3-oai
[-] #48151 Add item anchors to `thread/items/list` pagination @btraut-openai
[-] #48155 Preserve filesystem denials when preparing approved commands @viyatb-oai
[-] #48157 Allow Windows daemon launches with residual job membership @etraut-openai
[-] #48158 Fix Guardian retained context spacing and empty assistant handling @olliem-oai
[-] #48168 Generate unique exec-server process IDs for every request @sdcoffey
[compaction] #48174 Preserve usage limit windows in turn and compaction analytics @rhan-oai
[permissions] #48176 Protect `.aws` directories under sandbox writable roots @jackz100
[-] #48187 Fix zsh alias quoting in sourced shell snapshots @jif-oai
[-] #48190 Bound agent message board SSE frames before parsing @jif-oai
[-] #48197 Optimize `blake3` in Bazel fastbuilds @jif-oai
[-] #48198 Honor execution environment proxy requirements @seanh-oai
[-] #48199 Keep archived threads with empty previews visible in listings @acrognale-oai
[-] #48200 Extract Responses header conversion into a shared module @anp-oai
[-] #48205 Dismiss viewed TUI warnings when closing the viewer @fcoury-oai
[-] #48206 Add a keep-and-next action to the warnings viewer @fcoury-oai
[-] #48207 Preserve queued output for observers during code-mode termination @pakrym-oai
[-] #48211 Keep Codex visible during external editor handoff @etraut-openai
[-] #48213 Isolate executable fixture copies in CLI tests on Linux @jif-oai
[-] #48222 Preserve late result metadata for truncated code-mode calls @ningyi-oai
[compaction] #48224 Preserve model and access program pairs during compaction @jamy-OAI
[-] #48229 Extract Responses failure parsing into a dedicated module @anp-oai
[mcp] #48238 Suppress console windows for local Windows MCP servers @malsamiri-oai
[-] #48272 Prevent Windows daemon launches from retaining launcher stdio @zm-oai
[-] #48318 Keep TUI reconnect attempts running until the shared deadline @etraut-openai
[provider] #48344 Preserve tool metadata for OpenAI provider endpoint overrides @peilin-openai
[-] #48350 Display reconnect commands on a separate line @etraut-openai
[-] #48352 Show turn tips while working and after completion in the TUI @fcoury-oai
[skills] #48353 Stabilize skill catalogs across executor availability changes @vkg-oai
[-] #48469 Default to copying transcript selections in more terminals @fcoury-oai
[-] #48483 Prevent console windows for piped Windows child processes @fcoury-oai
[-] #48489 Fix Mermaid shape, relationship, and state description parsing @etraut-openai
[-] #48491 Fall back to embedded mode under restrictive Windows launchers @fcoury-oai
[-] #48502 Fix ChatGPT browser sign-in for local app servers @etraut-openai
[-] #48508 Preserve WebSocket continuations when steering a turn @pakrym-oai
[-] #48513 Refresh the TUI welcome screen for new sessions @fcoury-oai
[permissions] #48531 Add context to Windows sandbox runtime registration errors @zm-oai
[-] #48544 Make onboarding login links easier to copy @etraut-openai
[-] #48547 Fade blossom replays back to the idle state @fcoury-oai
[-] #48548 Preserve table cell source metadata through TUI rendering @fcoury-oai
[-] #48549 Preserve Markdown tables and whitespace when copying TUI responses @fcoury-oai
[-] #48551 Fix TUI math rendering for zero and big wedge expressions @etraut-openai
[-] #48560 Keep working tips stable during transcript interaction @fcoury-oai
[-] #48562 Use a consistent borderless session header in the TUI @fcoury-oai
[-] #48565 Allow macOS TLS trust evaluation in network-enabled Seatbelt profiles @winston-openai
[-] #48568 Allow exec-server to proxy permitted private IPs upstream @open-matt
[-] #48574 Preserve deferred tool namespace names before descriptions @adaley-openai
[-] #48575 Allow provisioned executors more time to come online @richardopenai
[plugins,skills,behavior-change] #48604 Remove the bundled `plugin-creator` skill @martinauyeung-oai
[-] #48611 Centralize persistent mode enablement checks @alishobeiri-oai
[behavior-change] #48621 Remove follow-up prompt suggestions from the TUI @etraut-openai
[-] #48623 Preserve empty Markdown list markers in the TUI @etraut-openai
[-] #48626 Stop showing previous-session summaries when switching TUI sessions @etraut-openai
[-] #48628 Preserve blank TUI sessions when switching tasks @etraut-openai
[-] #48643 Set the provisioned macOS CLI bundle name to ChatGPT @riley-oai
[-] #48646 Fix the session-start helper call in the command center test @etraut-openai
[behavior-change] #48686 Remove WebSocket headers and tool payloads from info logs @chess-oai
[mcp] #48724 Prevent Linux ETXTBSY races in MCP stdio tests @jif-oai
[-] #48725 Retain confirmed Code Mode messages for Guardian reviews @ankushg
[-] #48727 Centralize executable fixture creation to avoid Linux ETXTBSY races @jif-oai
[-] #48754 Render `/status` without borders and wrap long values @fcoury-oai
[-] #48757 Match TUI status shimmer timing to desktop headers @fcoury-oai
[compaction] #48761 Show hidden output line counts in compact terminal activity @fcoury-oai
[mcp] #48764 Preserve MCP app resource URIs without defaulting display mode @victor-openai
[-] #48772 Fix Unix socket connections through long symlink paths @etraut-openai
[-] #48775 Match pinned transcript headers to the original prompt style @etraut-openai
[behavior-change] #48776 Remove the `current` badge from TUI task rows @etraut-openai
[compaction] #48779 Preserve independent Guardian history across parent compaction @felixxia-oai
[mcp] #48783 Add single-server MCP status discovery with thread connection reuse @victor-openai
[-] #48796 Add opt-in structured errors for Guardian circuit-breaker interruptions @won-openai
[-] #48799 Fix SGR mouse reporting for Windows terminal capture @etraut-openai
[-] #48800 Use the terminal palette for ordered Markdown list markers @etraut-openai
[-] #48805 Allow transcript wheel scrolling while a modal is open @fcoury-oai
[statusline] #48807 Show short turn durations in TUI completion footers @fcoury-oai
[-] #48812 Add history-aware prewarming for idle threads @vkg-oai
[-] #48814 Preserve punctuation and semicolons in Mermaid labels @etraut-openai
[skills] #48819 Use explicit histogram buckets for tool and skill context metrics @mzeng-openai
[-] #48824 Keep voice RTP timestamps aligned to 20 ms packets @bc-openai
[term:kitty] #48827 Show a hand pointer over transcript links in Ghostty and Kitty @bc-openai
[-] #48828 Allow archiving threads before their first turn @bc-openai
[permissions] #48829 Wait briefly for the Windows sandbox provisioning service to start @zm-oai
[-] #48830 Show a short, neutral TUI interruption notice @fcoury-oai
[-] #48895 Expand native Mermaid flowchart syntax support @etraut-openai
[-] #48973 Isolate realtime auth fallback test from startup prewarm @jif-oai
[-] #48982 Prevent message-board notifications from reopening final answers @eknight-oai

Baseline file: /example/state/baseline.json
Baseline unchanged; add --through VERSION --commit after presenting this window.
Local snapshot; releases outside this file are not searched.
Archive coverage: 0.159.0 through 0.159.3
Source: Frozen public archive or explicitly synthetic fixture; see cases.json
