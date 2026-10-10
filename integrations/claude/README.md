# Agent skill

`skills/mothership/` is a skill that lets Claude Code (and other agents that read
skills) control mothership: lighting, thermal modes, fans, G-Mode, CPU limits,
profiles, and, only when you explicitly ask, the flash-writing and restarting
commands (power-button colours, macros, firmware updates, graphics mode).

Install it for your user. From the package:

```sh
mkdir -p ~/.claude/skills
ln -s /usr/share/mothership/claude/skills/mothership ~/.claude/skills/mothership
```

or from a checkout of this repository:

```sh
cp -r integrations/claude/skills/mothership ~/.claude/skills/
```

Codex reads skills from `~/.agents/skills`; link or copy the same folder there
(`ln -s /usr/share/mothership/claude/skills/mothership ~/.agents/skills/mothership`).

The skill drives the `mothership` command, so `mothershipd` must be running
(`systemctl --user enable --now mothershipd`).
