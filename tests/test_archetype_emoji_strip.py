"""Tests for emoji stripping from archetype names."""

import pytest

from services.archetype import ArchetypeService


class TestGetOrCreateByNameStripsEmoji:
    def test_emoji_prefix_stripped(self, arch_svc):
        arch = arch_svc.get_or_create_by_name("🟢🔵🐸 Bogles")
        assert arch.name == "Bogles"

    def test_clean_name_unchanged(self, arch_svc):
        arch = arch_svc.get_or_create_by_name("Red Kuldotha")
        assert arch.name == "Red Kuldotha"

    def test_multiple_emoji_stripped(self, arch_svc):
        arch = arch_svc.get_or_create_by_name("🔴🔵🐍 UR Skred")
        assert arch.name == "UR Skred"

    def test_emoji_only_name_becomes_empty_then_stored_as_empty(self, arch_svc):
        # Edge case: if someone passes only emojis, name becomes ""
        arch = arch_svc.get_or_create_by_name("🔴🔵")
        assert arch.name == ""

    def test_deduplication_returns_existing(self, arch_svc):
        existing = arch_svc.get_or_create_by_name("Bogles")
        with_emoji = arch_svc.get_or_create_by_name("🟢🔵🐸 Bogles")
        assert with_emoji.id == existing.id
        assert with_emoji.name == "Bogles"

    def test_whitespace_around_name_stripped(self, arch_svc):
        arch = arch_svc.get_or_create_by_name("  Burn  ")
        assert arch.name == "Burn"
