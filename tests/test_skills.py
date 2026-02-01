"""Tests for the skills module."""

import pytest


class TestSkillPath:
    """Tests for get_skill_path function."""

    def test_get_skill_path_existing_skill(self):
        """Test getting path for an existing skill."""
        from claim_agent.skills import get_skill_path
        
        path = get_skill_path("router")
        assert path.exists()
        assert path.suffix == ".md"
        assert path.stem == "router"

    def test_get_skill_path_nonexistent_skill(self):
        """Test getting path for non-existent skill raises FileNotFoundError."""
        from claim_agent.skills import get_skill_path
        
        with pytest.raises(FileNotFoundError) as exc_info:
            get_skill_path("nonexistent_skill_xyz")
        
        assert "nonexistent_skill_xyz" in str(exc_info.value)


class TestLoadSkillContent:
    """Tests for load_skill_content function."""

    def test_load_skill_content_returns_string(self):
        """Test loading skill content returns a non-empty string."""
        from claim_agent.skills import load_skill_content
        
        content = load_skill_content("router")
        assert isinstance(content, str)
        assert len(content) > 0
        assert "## Role" in content

    def test_load_skill_content_nonexistent(self):
        """Test loading non-existent skill raises FileNotFoundError."""
        from claim_agent.skills import load_skill_content
        
        with pytest.raises(FileNotFoundError):
            load_skill_content("nonexistent_skill_xyz")


class TestParseSkillSection:
    """Tests for parse_skill_section function."""

    def test_parse_skill_section_role(self):
        """Test parsing Role section from content."""
        from claim_agent.skills import parse_skill_section
        
        content = """# Test Skill

## Role
Test Role Title

## Goal
Test goal description.
"""
        role = parse_skill_section(content, "Role")
        assert role == "Test Role Title"

    def test_parse_skill_section_goal(self):
        """Test parsing Goal section from content."""
        from claim_agent.skills import parse_skill_section
        
        content = """# Test Skill

## Role
Test Role

## Goal
Multi-line goal description.
With more details here.

## Backstory
Some backstory.
"""
        goal = parse_skill_section(content, "Goal")
        assert "Multi-line goal" in goal
        assert "With more details" in goal

    def test_parse_skill_section_not_found(self):
        """Test parsing non-existent section returns None."""
        from claim_agent.skills import parse_skill_section
        
        content = """# Test Skill

## Role
Test Role
"""
        result = parse_skill_section(content, "NonExistent")
        assert result is None


class TestLoadSkill:
    """Tests for load_skill function."""

    def test_load_skill_returns_dict(self):
        """Test load_skill returns a dictionary with expected keys."""
        from claim_agent.skills import load_skill
        
        skill = load_skill("router")
        assert isinstance(skill, dict)
        assert "role" in skill
        assert "goal" in skill
        assert "backstory" in skill
        assert "full_content" in skill
        assert "tools" in skill

    def test_load_skill_role_is_string(self):
        """Test that role is a non-empty string."""
        from claim_agent.skills import load_skill
        
        skill = load_skill("intake")
        assert isinstance(skill["role"], str)
        assert len(skill["role"]) > 0

    def test_load_skill_full_content(self):
        """Test that full_content contains the entire file."""
        from claim_agent.skills import load_skill
        
        skill = load_skill("router")
        assert "## Role" in skill["full_content"]
        assert "## Goal" in skill["full_content"]


class TestListSkills:
    """Tests for list_skills function."""

    def test_list_skills_returns_list(self):
        """Test list_skills returns a list."""
        from claim_agent.skills import list_skills
        
        skills = list_skills()
        assert isinstance(skills, list)
        assert len(skills) > 0

    def test_list_skills_contains_known_skills(self):
        """Test list_skills contains expected skill names."""
        from claim_agent.skills import list_skills
        
        skills = list_skills()
        assert "router" in skills
        assert "intake" in skills
        assert "policy_checker" in skills
        assert "damage_assessor" in skills

    def test_list_skills_excludes_readme(self):
        """Test that README.md is excluded from list."""
        from claim_agent.skills import list_skills
        
        skills = list_skills()
        assert "README" not in skills


class TestSkillConstants:
    """Tests for skill name constants."""

    def test_skill_constants_are_strings(self):
        """Test that skill constants are strings."""
        from claim_agent.skills import (
            ROUTER,
            INTAKE,
            POLICY_CHECKER,
            ASSIGNMENT,
            SEARCH,
            SIMILARITY,
            RESOLUTION,
            PATTERN_ANALYSIS,
            CROSS_REFERENCE,
            FRAUD_ASSESSMENT,
            DAMAGE_ASSESSOR,
            VALUATION,
            PAYOUT,
            SETTLEMENT,
            PARTIAL_LOSS_DAMAGE_ASSESSOR,
            REPAIR_ESTIMATOR,
            REPAIR_SHOP_COORDINATOR,
            PARTS_ORDERING,
            REPAIR_AUTHORIZATION,
            ESCALATION,
        )
        
        constants = [
            ROUTER, INTAKE, POLICY_CHECKER, ASSIGNMENT, SEARCH,
            SIMILARITY, RESOLUTION, PATTERN_ANALYSIS, CROSS_REFERENCE,
            FRAUD_ASSESSMENT, DAMAGE_ASSESSOR, VALUATION, PAYOUT,
            SETTLEMENT, PARTIAL_LOSS_DAMAGE_ASSESSOR, REPAIR_ESTIMATOR,
            REPAIR_SHOP_COORDINATOR, PARTS_ORDERING, REPAIR_AUTHORIZATION,
            ESCALATION,
        ]
        
        for constant in constants:
            assert isinstance(constant, str)
            assert len(constant) > 0

    def test_skill_constants_match_files(self):
        """Test that skill constants correspond to actual skill files."""
        from claim_agent.skills import ROUTER, INTAKE, list_skills, load_skill
        
        # Verify these skills can be loaded
        router_skill = load_skill(ROUTER)
        assert router_skill["role"] is not None
        
        intake_skill = load_skill(INTAKE)
        assert intake_skill["role"] is not None


class TestLoadSkillWithContext:
    """Tests for load_skill_with_context function."""

    def test_load_skill_without_rag(self):
        """Test loading skill without RAG context."""
        from claim_agent.skills import load_skill_with_context
        
        skill = load_skill_with_context("router", use_rag=False)
        assert isinstance(skill, dict)
        assert skill["role"] is not None
        assert skill["goal"] is not None

    def test_load_skill_with_rag_failure_fallback(self):
        """Test that RAG failure falls back to base skill."""
        from claim_agent.skills import load_skill_with_context
        
        # Even if RAG fails to load, we should still get the base skill
        skill = load_skill_with_context(
            "router",
            state="NonExistentState",
            use_rag=True,
        )
        assert isinstance(skill, dict)
        assert skill["role"] is not None


class TestGetRagProvider:
    """Tests for get_rag_provider function."""

    def test_get_rag_provider_returns_provider(self):
        """Test get_rag_provider returns a RAGContextProvider."""
        from claim_agent.skills import get_rag_provider
        from claim_agent.rag.context import RAGContextProvider
        
        provider = get_rag_provider()
        assert isinstance(provider, RAGContextProvider)

    def test_get_rag_provider_singleton(self):
        """Test that get_rag_provider returns the same instance."""
        from claim_agent.skills import get_rag_provider
        
        provider1 = get_rag_provider()
        provider2 = get_rag_provider()
        assert provider1 is provider2
