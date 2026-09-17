"""Test Self-Improving Skills Engine & Progressive Disclosure."""
from pathlib import Path
import pytest

from owibot.agent.skills import SkillsEngine, sanitize_skill_name
from owibot.agent.tools import LocalTools


def test_sanitize_skill_name():
    assert sanitize_skill_name("Deploy Staging 2026!") == "deploy-staging-2026"
    assert sanitize_skill_name("---test---") == "test"
    with pytest.raises(ValueError):
        sanitize_skill_name("   ")


def test_skills_engine_save_load_patch_delete(tmp_path):
    engine = SkillsEngine(tmp_path)

    # Save skill
    res = engine.save_skill(
        name="docker-build",
        description="Cara build container docker",
        procedure="1. Jalankan docker build -t app .\n2. Tag image.",
        always=False,
    )
    assert "OK" in res
    assert "docker-build" in engine.index_summary()

    # Load skill
    loaded = engine.load_skill("docker-build")
    assert loaded is not None
    assert "docker build -t app" in loaded

    # Patch skill
    patch_res = engine.patch_skill(
        name="docker-build",
        search_text="2. Tag image.",
        replacement_text="2. Jalankan docker tag app:v1.",
    )
    assert "OK" in patch_res
    updated = engine.load_skill("docker-build")
    assert "docker tag app:v1" in updated

    # Delete skill
    deleted = engine.delete_skill("docker-build")
    assert deleted is True
    assert engine.load_skill("docker-build") is None


def test_skills_engine_references(tmp_path):
    engine = SkillsEngine(tmp_path)
    engine.save_skill("k8s-ops", "Kubernetes operation", "Deploy manifests")

    # Create reference file
    ref_dir = tmp_path / "skills" / "k8s-ops" / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "cheatsheet.md").write_text("# Kubectl Cheatsheet\nkubectl get pods", encoding="utf-8")

    content = engine.load_skill_reference("k8s-ops", "references/cheatsheet.md")
    assert "kubectl get pods" in content

    # Traversal attempt
    with pytest.raises(ValueError):
        engine.load_skill_reference("k8s-ops", "../../secret.txt")


def test_local_tools_skill_manage_and_view(tmp_path):
    tools = LocalTools(tmp_path)

    # Manage: save
    save_out = tools.skill_manage(
        action="save",
        name="ci-pipeline",
        description="Pipeline CI/CD",
        procedure="Run pytest dan ruff check",
    )
    assert "OK" in save_out

    # View
    view_out = tools.skill_view(name="ci-pipeline")
    assert "Pipeline CI/CD" in view_out or "pytest" in view_out

    # Manage: list
    list_out = tools.skill_manage(action="list")
    assert "ci-pipeline" in list_out
