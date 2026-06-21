from tron.agents.security_iso import SecurityISO
from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
from tron.schemas.verification import Blueprint, BlueprintScope, VulnerabilityType

def test_security_iso_not_in_scope_prompt():
    config = ISOConfig(
        specialization=ISOSpecialization.SECURITY,
        agent_id="test-agent",
        model_provider=LLMProvider.ANTHROPIC,
        model_name="claude-3",
    )
    secrets = {"llm/anthropic-key": "test-key"}
    agent = SecurityISO(config, secrets)
    
    blueprint = Blueprint(
        id="test-blueprint",
        name="Test Blueprint",
        description="Test Description",
        scope=BlueprintScope(
            file_patterns=["*.py"],
            check_types=[VulnerabilityType.SQL_INJECTION],
            languages=["python"],
        ),
        not_in_scope=["tests/*", "vendor/*"],
    )
    
    prompt = agent._build_prompt(blueprint, {"app.py": "print('hello')"}, {})
    
    assert "STRICT SCOPE ENFORCEMENT" in prompt
    assert "'tests/*'" in prompt
    assert "'vendor/*'" in prompt
    assert "EXPLICITLY OUT OF SCOPE" in prompt

def test_security_iso_no_not_in_scope_prompt():
    config = ISOConfig(
        specialization=ISOSpecialization.SECURITY,
        agent_id="test-agent",
        model_provider=LLMProvider.ANTHROPIC,
        model_name="claude-3",
    )
    secrets = {"llm/anthropic-key": "test-key"}
    agent = SecurityISO(config, secrets)
    
    blueprint = Blueprint(
        id="test-blueprint",
        name="Test Blueprint",
        description="Test Description",
        scope=BlueprintScope(
            file_patterns=["*.py"],
            check_types=[VulnerabilityType.SQL_INJECTION],
            languages=["python"],
        ),
        not_in_scope=[],
    )
    
    prompt = agent._build_prompt(blueprint, {"app.py": "print('hello')"}, {})
    
    assert "STRICT SCOPE ENFORCEMENT" not in prompt
