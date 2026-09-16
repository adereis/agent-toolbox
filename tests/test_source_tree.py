"""Source-tree invariants: documentation links and deployable profile content."""

from pathlib import Path
import re
import tomllib
import unittest


REPO = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)>\s]+)>?\s*(?:\"[^\"]*\")?\)")
EXTERNAL = ("http://", "https://", "mailto:", "#")

# Authentication profiles install into the user's CODEX_HOME, so they carry
# provider selection only. Personal defaults belong in examples/codex/.
PROFILE_KEYS = {"model_provider", "model_providers", "forced_login_method",
                "preferred_auth_method"}


def prose(text):
    """Drop fenced blocks so sample commands are not read as live links."""
    return "".join(part for index, part in enumerate(FENCE.split(text)) if index % 3 == 0)


def names(table):
    """Every key name at any depth, so a nested pin cannot hide in a table."""
    found = set()
    for key, value in table.items():
        found.add(key)
        if isinstance(value, dict):
            found |= names(value)
    return found


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_links_resolve_in_an_uninstalled_checkout(self):
        """An agent reads a skill from the checkout before anything is installed."""
        broken = []
        for document in sorted(REPO.rglob("*.md")):
            if ".git" in document.parts:
                continue
            for match in LINK.finditer(prose(document.read_text(errors="replace"))):
                target = match.group(1)
                if target.startswith(EXTERNAL):
                    continue
                path = (document.parent / target.split("#")[0]).resolve()
                if not path.exists():
                    broken.append(f"{document.relative_to(REPO)} -> {target}")
        self.assertEqual(broken, [], "Relative links must resolve without installing; "
                                     "harness skills reach shared text through a "
                                     "committed references/ symlink")


class CodexProfileTests(unittest.TestCase):
    def test_profiles_carry_provider_settings_only(self):
        """A personal model pin here would follow the profile onto every machine."""
        for profile in sorted((REPO / "harnesses/codex/profiles").glob("*.config.toml")):
            with self.subTest(profile=profile.name):
                keys = set(tomllib.loads(profile.read_text()))
                self.assertEqual(keys - PROFILE_KEYS, set(),
                                 f"{profile.name} may hold provider and authentication "
                                 "settings only; record personal defaults in "
                                 "examples/codex/config.toml instead")

    def test_profiles_do_not_restate_personal_preferences(self):
        """A pin nested in a provider table is as misplaced as a top-level one."""
        personal = names(tomllib.loads((REPO / "examples/codex/config.toml").read_text()))
        for profile in sorted((REPO / "harnesses/codex/profiles").glob("*.config.toml")):
            with self.subTest(profile=profile.name):
                overlap = names(tomllib.loads(profile.read_text())) & personal
                self.assertEqual(overlap, set(),
                                 f"{profile.name} restates personal keys {sorted(overlap)}; "
                                 "the subscription profile has no matching key, so the "
                                 "model would change silently when switching profiles")


if __name__ == "__main__":
    unittest.main()
