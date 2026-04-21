"""TDD tests for Worker openclaw.json context pruning patch.

The same transformation is applied in two places:
  - deploy/hiclaw/manager-init-internal.sh  (step 2b — auto-init, runs on every startup)
  - deploy/hiclaw/init-workers.sh           (step 3b — manual fallback)

These tests verify the transformation is correct before embedding it in both scripts.
"""
import copy


def apply_context_pruning_patch(cfg: dict) -> dict:
    """Apply context pruning + concurrency patch to openclaw.json config dict.

    Mirrors the Python snippet to be added to step 2b / step 3b.
    """
    cfg = copy.deepcopy(cfg)
    if "agents" not in cfg:
        cfg["agents"] = {}
    if "defaults" not in cfg["agents"]:
        cfg["agents"]["defaults"] = {}
    defaults = cfg["agents"]["defaults"]

    defaults["maxConcurrent"] = 8
    defaults["contextTokens"] = 40000
    defaults["contextPruning"] = {
        "mode": "cache-ttl",
        "keepLastAssistants": 10,
        "softTrimRatio": 0.7,
        "hardClearRatio": 0.9,
        "hardClear": {
            "enabled": True,
            "placeholder": "[历史对话已自动压缩，当前任务上下文完整保留]",
        },
    }
    defaults["subagents"] = {"maxConcurrent": 8}
    return cfg


def test_sets_max_concurrent_to_8():
    cfg = {"agents": {"defaults": {"maxConcurrent": 4}}}
    result = apply_context_pruning_patch(cfg)
    assert result["agents"]["defaults"]["maxConcurrent"] == 8


def test_sets_context_tokens_to_40000():
    result = apply_context_pruning_patch({})
    assert result["agents"]["defaults"]["contextTokens"] == 40000


def test_sets_context_pruning_mode_cache_ttl():
    result = apply_context_pruning_patch({})
    assert result["agents"]["defaults"]["contextPruning"]["mode"] == "cache-ttl"


def test_sets_soft_trim_ratio():
    result = apply_context_pruning_patch({})
    assert result["agents"]["defaults"]["contextPruning"]["softTrimRatio"] == 0.7


def test_sets_hard_clear_ratio():
    result = apply_context_pruning_patch({})
    assert result["agents"]["defaults"]["contextPruning"]["hardClearRatio"] == 0.9


def test_hard_clear_enabled_with_chinese_placeholder():
    result = apply_context_pruning_patch({})
    hc = result["agents"]["defaults"]["contextPruning"]["hardClear"]
    assert hc["enabled"] is True
    assert "历史对话已自动压缩" in hc["placeholder"]


def test_sets_subagents_max_concurrent_to_8():
    result = apply_context_pruning_patch({})
    assert result["agents"]["defaults"]["subagents"]["maxConcurrent"] == 8


def test_preserves_existing_model_config():
    cfg = {"agents": {"defaults": {"model": {"primary": "hiclaw-gateway/MiniMax-M2.7"}}}}
    result = apply_context_pruning_patch(cfg)
    assert result["agents"]["defaults"]["model"]["primary"] == "hiclaw-gateway/MiniMax-M2.7"


def test_idempotent_when_applied_twice():
    result = apply_context_pruning_patch(apply_context_pruning_patch({}))
    assert result["agents"]["defaults"]["contextTokens"] == 40000
    assert result["agents"]["defaults"]["maxConcurrent"] == 8
